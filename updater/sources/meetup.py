"""Meetup Canggu source for the Bali events pipeline.

Scrapes the public discovery page ``/find/id--canggu/`` plus one
detail page per dated event (``/<group>/events/<id>/``). Exposes
``fetch() -> list[dict]`` of *raw* events; normalization (uids, UTC
times, enums) happens downstream.

Verified 2026-09-27: listing returns HTTP 200 with plain GET (no
login, no JS, no bot wall). Dated ``/events/<id>/`` links appear in
raw ``<a>`` anchors; richer ISO-date + venue + group records are
embedded in the ``__NEXT_DATA__`` JSON blob. Detail pages render
title/date/venue/host in server-side HTML.

Recurring series (e.g. "Every 1st Friday ... until <date>") expand to
dated instances inside the discovery window (today -> +14d).

requests + beautifulsoup only. No browser, no login, no JS.
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

SOURCE = "meetup"
TIER = 2

BASE_URL = "https://www.meetup.com"
LISTING_URL = BASE_URL + "/find/id--canggu/"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://www.meetup.com/find/id--canggu/)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_EVENT_HREF_RE = re.compile(r"^/[a-z0-9-]+/events/\d+/?$", re.I)

# Discovery window for recurrence expansion (today -> +14d).
_WINDOW_DAYS = 14

# Obvious cross-post spam: far-away organizer groups dumping generic
# tour events onto the Canggu page (vague "Kuta, Bali" venue, no local
# organizer presence). Rejected at hoax-check.
_SPAM_GROUP_RES = (
    "adventure-diaries",
    "nomadic-escapades",
    "offbeat-adventure-junkies",
)

_EVERY_MONTH_WDAY_RE = re.compile(
    r"every\s+(first|1st|second|2nd|third|3rd|fourth|4th|last)\s+"
    r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)
_UNTIL_RE = re.compile(
    r"until\s+(january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})",
    re.I,
)
_ORDINAL = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3,
            "3rd": 3, "fourth": 4, "4th": 4, "last": -1}
_WDAY = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
         "friday": 4, "saturday": 5, "sunday": 6}


def _text(node) -> str:
    """Single-line cleaned text for a bs4 node (None-safe)."""
    if node is None:
        return ""
    raw = node if isinstance(node, str) else node.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", raw).strip()


def _get(session: requests.Session, url: str) -> str | None:
    """GET url, returning response text or None on any failure."""
    try:
        resp = session.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.text or None
    except Exception as exc:  # per-page failure must not kill the run
        print(f"[{SOURCE}] GET failed for {url}: {exc}", file=sys.stderr)
        return None


def _next_data(html: str):
    """Parse the ``__NEXT_DATA__`` JSON blob (None on miss)."""
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.S,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _walk(node, pred, hits: list):
    """Collect nodes (dicts) matching pred via recursive walk."""
    if isinstance(node, dict):
        if pred(node):
            hits.append(node)
        for value in node.values():
            _walk(value, pred, hits)
    elif isinstance(node, list):
        for value in node:
            _walk(value, pred, hits)


def _collect_links(html: str) -> list[str]:
    """Dated detail links (``/<group>/events/<id>/``) from listing."""
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").split("?")[0]
        if not _EVENT_HREF_RE.match(href):
            continue
        url = BASE_URL + href
        if url in seen:
            continue
        seen.add(url)
        links.append(url)
    # Embedded JSON carries the same dated refs; union as fallback.
    blob = _next_data(html)
    if blob is not None:
        found: list = []
        _walk(blob,
              lambda d: isinstance(d.get("eventUrl"), str)
              and "/events/" in d["eventUrl"],
              found)
        for node in found:
            url = node["eventUrl"].split("?")[0]
            if url.startswith("https://www.meetup.com/") and url not in seen:
                seen.add(url)
                links.append(url)
    return links


def _map_category(title: str, group: str, description: str) -> str:
    """Map title/group/description to a raw category."""
    low = f"{title} {group} {description}".lower()
    if any(k in low for k in ("bitcoin", "crypto", "web3", "blockchain",
                              "startup", "tech", "coding", "developer",
                              "software", " ai ", "artificial intelligence")):
        return "tech"
    if any(k in low for k in ("party", "club", "nightlife", "dj",
                              "latin night", "beach club")):
        return "party"
    return "community"


def _parse_detail(html: str, url: str) -> dict | None:
    """Build a raw event dict from an event detail page (None = skip)."""
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    title = _text(h1)
    if not title:
        return None

    # Hoax-check: drop cross-post spam groups (no local organizer).
    slug = url.split("meetup.com/")[-1].split("/")[0].lower()
    if slug in _SPAM_GROUP_RES:
        print(f"[{SOURCE}] skipping cross-post spam group: {url}",
              file=sys.stderr)
        return None

    body = soup.get_text(" ", strip=True)
    body_low = body.lower()
    if "this event was canceled" in body_low or \
            "this event has been cancelled" in body_low:
        print(f"[{SOURCE}] skipping canceled event: {url}", file=sys.stderr)
        return None

    # Best date first: embedded ISO dateTime (has offset); fall back to
    # the rendered "Friday, Oct 2 · 4:00 PM to 6:00 PM WIB" line.
    start = ""
    blob = _next_data(html)
    if blob is not None:
        dated: list = []
        _walk(blob,
              lambda d: isinstance(d.get("dateTime"), str),
              dated)
        if dated:
            start = str(dated[0]["dateTime"]).strip()
    if not start:
        m = re.search(
            r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2})"
            r"\s*[·•-]\s*(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?",
            body, re.I,
        )
        if m:
            try:
                month = datetime.strptime(m.group(2)[:3], "%b").month
                year = datetime.now().year
                hour = int(m.group(4)) % 12 + (12 if m.group(6).upper() == "P" else 0)
                start = datetime(year, month, int(m.group(3)),
                                 hour, int(m.group(5) or 0)).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                start = ""
    if not start:
        return None  # undated: nothing to emit

    # Venue: embedded venue {name, address, city} beats rendered text.
    venue = ""
    if blob is not None:
        venues: list = []
        _walk(blob,
              lambda d: isinstance(d.get("name"), str)
              and isinstance(d.get("address"), str)
              and ("venue" in json.dumps(d)[:0] or True),
              venues)
        for node in venues:
            name = str(node.get("name") or "").strip()
            addr = str(node.get("address") or "").strip()
            city = str(node.get("city") or "").strip()
            if name and addr and "meetup" not in name.lower():
                venue = name + ", " + addr + (", " + city if city else "")
                break
    if not venue:
        m = re.search(
            r"([A-Z][^|]{3,60}(?:Beach|Canggu|Pererenan|Club|Bar|Cafe|Kitchen"
            r"|Project|Havana|Atlas)[^|]{0,80}?)\s*\|\s*"
            r"(Jl\.[^|]{5,120}|[A-Z][^|]{5,120}Badung[^|]{0,60})",
            body,
        )
        if m:
            venue = (_text(m.group(1)) + ", " + _text(m.group(2))).strip(" ,")
    if not venue:
        return None  # vague venue: reject per hoax-check rules

    group = ""
    if blob is not None:
        groups: list = []
        _walk(blob,
              lambda d: isinstance(d.get("name"), str)
              and isinstance(d.get("urlname"), str),
              groups)
        if groups:
            group = str(groups[0]["name"]).strip()
    if not group:
        m = re.search(r"by\s+([A-Z][^|·]{2,60})", body)
        group = m.group(1).strip() if m else ""

    description = ""
    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        description = og.get("content").strip()
    if not description:
        paras = sorted((_text(p) for p in soup.find_all("p")),
                       key=len, reverse=True)
        description = next((p for p in paras if len(p) > 40), "")
    if group and group.lower() not in description.lower():
        description = (description + f" (Organizer: {group})").strip()
    description = description[:4000]

    return {
        "name": title,
        "title": title,
        "start": start,
        "finish": None,
        "location": venue,
        "description": description,
        "area": venue,
        "category": _map_category(title, group, description),
        "cost": None,
        "free": None,
        "source_url": url,
        "status": "confirmed",
    }


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date | None:
    """Date of the nth (or last, n=-1) weekday of a month."""
    if n == -1:
        day = 28
        while True:
            try:
                cand = date(year, month, day + 1)
            except ValueError:
                break
            day += 1
        cand = date(year, month, day)
        while cand.weekday() != weekday:
            cand -= timedelta(days=1)
        return cand if cand.month == month else None
    cand = date(year, month, 1)
    while cand.weekday() != weekday:
        cand += timedelta(days=1)
    cand += timedelta(days=7 * (n - 1))
    return cand if cand.month == month else None


def _expand_monthly(event: dict, body_hint: str = "") -> list[dict]:
    """Expand an explicit monthly series to dated instances in the window.

    Only fires when the description (or hint) names a monthly weekday
    pattern like "every first Friday" with an end date. Extra instances
    copy the time-of-day forward month by month.
    """
    text = (event.get("description") or "") + " " + body_hint
    m = _EVERY_MONTH_WDAY_RE.search(text)
    if not m:
        return [event]
    n = _ORDINAL[m.group(1).lower()]
    weekday = _WDAY[m.group(2).lower()]
    try:
        base = datetime.fromisoformat(str(event["start"]).replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return [event]
    # Sanity: the dated instance must itself fall on the named pattern.
    expect = _nth_weekday(base.year, base.month, weekday, n)
    if expect is None or expect != base.date():
        return [event]
    until = None
    mu = _UNTIL_RE.search(text)
    if mu:
        try:
            month = datetime.strptime(mu.group(1)[:3], "%b").month
            until = date(int(mu.group(3)), month, int(mu.group(2)))
        except ValueError:
            until = None
    today = datetime.now().date()
    horizon = today + timedelta(days=_WINDOW_DAYS)
    out = [event] if base.date() >= today else []
    year, month = base.year, base.month
    while True:
        month += 1
        if month > 12:
            month = 1
            year += 1
        if date(year, month, 1) > horizon:
            break
        if until is not None and date(year, month, 1) > until:
            break
        day = _nth_weekday(year, month, weekday, n)
        if day is None or day < today or day > horizon:
            continue
        if until is not None and day > until:
            continue
        copy = dict(event)
        copy["start"] = day.strftime("%Y-%m-%d") + base.strftime("T%H:%M%z")
        copy["description"] = ((event.get("description") or "")
                               + " (monthly series)").strip()[:4000]
        out.append(copy)
        if len(out) > 3:
            break
    if len(out) > 1:
        print(f"[{SOURCE}] expanded monthly series "
              f"'{event['name']}': {len(out)} instances")
    return out


def fetch() -> list[dict]:
    """Fetch raw Canggu events from meetup.com.

    Returns a list of dicts (possibly empty). Raises RuntimeError when
    the listing yields zero dated links (parser assert: a redesign
    pages us instead of silently emptying the feed); per-page failures
    are logged and skipped.
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        listing_html = _get(session, LISTING_URL)
        if not listing_html:
            return []
        links = _collect_links(listing_html)
        if not links:
            raise RuntimeError(
                f"parser assert failed: no /events/<id> links on {LISTING_URL}"
            )

        events: list[dict] = []
        for index, url in enumerate(links):
            if index:
                time.sleep(1 + random.random())  # 1-2s between page fetches
            detail_html = _get(session, url)
            if not detail_html:
                continue
            try:
                event = _parse_detail(detail_html, url)
            except Exception as exc:
                print(f"[{SOURCE}] parse failed for {url}: {exc}",
                      file=sys.stderr)
                continue
            if event is None:
                continue
            events.extend(_expand_monthly(event, detail_html[:2000]))
        print(f"[{SOURCE}] {len(events)} events from {len(links)} details")
        return events
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"[{SOURCE}] fetch failed: {exc}", file=sys.stderr)
        return []
