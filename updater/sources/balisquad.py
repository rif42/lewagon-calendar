"""BaliSquad events source for the Bali events pipeline.

Scrapes the public listing at https://balisquad.com/event plus one
detail page per event (``/event/<slug-id>``). Exposes
``fetch() -> list[dict]`` of *raw* events; normalization (uids, UTC
times, enums) happens downstream.

Community/nomad layer (sports, socials, workshops, language exchange):
each detail page embeds an escaped schema.org ``Event`` JSON-LD payload
(``startDate``/``endDate`` in UTC, ``location`` Place + ``geo``,
``offers``/``price``) inside the Next.js flight data, plus server-
rendered date/venue/category markup. Pure-party entries corroborate
the covered nightlife layer and are kept under their non-nightlife
side only when the listing category chip says otherwise.

requests + beautifulsoup only. No browser, no login, no JS.
"""

from __future__ import annotations

import random
import re
import sys
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

SOURCE = "balisquad"
TIER = 1

BASE_URL = "https://balisquad.com"
LISTING_URL = BASE_URL + "/event"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://balisquad.com)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_DETAIL_RE = re.compile(r"^/event/(?![a-z]*$).{4,}")

# "Friday, September 25, 2026" + optional "8:00 PM - 10:00 PM".
_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{1,2}),\s+(\d{4})"
)
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?", re.I)

# Discovery window for recurrence expansion (today -> +14d).
_WINDOW_DAYS = 14
_MAX_EXPANSIONS = 3
_EVERY_WEEKDAY_RE = re.compile(
    r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I
)
_WEEKDAYS = (
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
)


def _text(node) -> str:
    """Single-line cleaned text for a bs4 node (None-safe)."""
    if node is None:
        return ""
    if isinstance(node, str):
        raw = node
    else:
        raw = node.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", raw).strip()


def _get(session: requests.Session, url: str) -> str | None:
    """GET url, returning response text or None on any failure."""
    try:
        resp = session.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        if not resp.text:
            return None
        return resp.text
    except Exception as exc:  # per-page failure must not kill the run
        print(f"[{SOURCE}] GET failed for {url}: {exc}", file=sys.stderr)
        return None


def _collect_links(html: str) -> list[str]:
    """Detail links (``/event/<slug-id>``) from the listing page."""
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").split("?")[0]
        if not _DETAIL_RE.match(href):
            continue
        url = BASE_URL + href
        if url in seen:
            continue
        seen.add(url)
        links.append(url)
    return links


def _collect_card_meta(html: str) -> dict[str, dict]:
    """Per-url listing-card facts: category chip, venue, date line, status."""
    soup = BeautifulSoup(html, "lxml")
    meta: dict[str, dict] = {}
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").split("?")[0]
        if not _DETAIL_RE.match(href):
            continue
        url = BASE_URL + href
        text = anchor.get_text(" | ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        chip = ""
        badge = anchor.select_one("span.rounded-full, span.inline-flex.rounded-full")
        if badge:
            chip = _text(badge)
        meta[url] = {"chip": chip, "text": text}
    return meta


def _unescape(value: str) -> str:
    """Decode the ``\\uXXXX`` / ``\\"`` escapes of flight-data JSON."""
    try:
        return value.encode("utf-8").decode("unicode_escape", errors="ignore")
    except Exception:
        return value


def _ld_field(html: str, field: str) -> str:
    """Extract an escaped ``\\"field\\":\\"value\\"`` from flight data."""
    m = re.search(r'\\\\"%s\\\\":\\\\"([^"\\\\]+)' % re.escape(field), html)
    if m:
        return _unescape(m.group(1)).strip()
    m = re.search(r'"%s":"([^"\\]+)"' % re.escape(field), html)
    return m.group(1).strip() if m else ""


def _map_category(chip: str, text: str) -> str:
    """Map a listing category chip (+ title text) to a raw category."""
    low = f"{chip} {text}".lower()
    if "sport" in low or "fitness" in low or "volleyball" in low or "badminton" in low:
        return "sport"
    if "wellness" in low or "yoga" in low or "retreat" in low or "meditation" in low:
        return "wellness"
    if "food" in low or "dining" in low or "brunch" in low or "coffee" in low:
        return "food"
    if (
        "art" in low
        or "cultur" in low
        or "music" in low
        or "exhibition" in low
        or "workshop" in low
        or "language" in low
        or "class" in low
    ):
        return "art"
    if "tech" in low or "coworking" in low or "startup" in low or "coding" in low:
        return "tech"
    if "party" in low or "club" in low or "nightlife" in low or "dj" in low:
        return "party"
    return "community"


def _parse_card_datetime(text: str) -> str:
    """'Fri | Sep 25 | 4:00 PM' (+ implied current year) -> ISO ('' on miss)."""
    m = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2})\s*[|·•-]?\s*"
        r"(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?",
        text, re.I,
    )
    if not m:
        return ""
    mon, day, hour, minute, ampm = m.groups()
    try:
        month = datetime.strptime(mon[:3], "%b").month
        year = datetime.now().year
        hour = int(hour) % 12 + (12 if ampm.upper() == "P" else 0)
        return datetime(year, month, int(day), hour, int(minute or 0)).strftime(
            "%Y-%m-%d %H:%M"
        )
    except ValueError:
        return ""


def _parse_detail_datetime(soup: BeautifulSoup) -> tuple[str, str]:
    """Rendered 'Friday, September 25, 2026' + '8:00 PM - 10:00 PM' -> ISO pair."""
    date_line, time_line = "", ""
    for p in soup.find_all("p", class_=re.compile(r"font-semibold")):
        t = _text(p)
        if _DATE_RE.search(t):
            date_line = t
            sib = p.find_next_sibling("p")
            if sib:
                time_line = _text(sib)
            break
    m = _DATE_RE.search(date_line)
    if not m:
        return "", ""
    try:
        base = datetime.strptime(
            "%s %s, %s" % (m.group(1), m.group(2), m.group(3)), "%B %d, %Y"
        )
    except ValueError:
        return "", ""
    times = _TIME_RE.findall(time_line)
    if not times:
        return base.strftime("%Y-%m-%d %H:%M"), ""
    def _to_time(t):
        hour, minute, ampm = t
        return (int(hour) % 12 + (12 if ampm.upper() == "P" else 0), int(minute or 0))
    start_h, start_m = _to_time(times[0])
    start = base.replace(hour=start_h, minute=start_m).strftime("%Y-%m-%d %H:%M")
    finish = ""
    if len(times) > 1:
        end_h, end_m = _to_time(times[1])
        end = base.replace(hour=end_h, minute=end_m)
        if end <= base.replace(hour=start_h, minute=start_m):
            end += timedelta(days=1)  # overnight session
        finish = end.strftime("%Y-%m-%d %H:%M")
    return start, finish


def _parse_detail(html: str, url: str, card: dict) -> dict | None:
    """Build a raw event dict from an event detail page (None = skip)."""
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    title = _text(h1)
    if not title:
        return None

    # Skip non-English titles the pipeline cannot curate (e.g. Cyrillic).
    if re.search(r"[\u0400-\u04FF\u4e00-\u9fff]", title):
        print(f"[{SOURCE}] skipping non-English title: {url}", file=sys.stderr)
        return None

    status = "confirmed"
    body_low = soup.get_text(" ", strip=True).lower()
    if "cancelled" in body_low or "canceled" in body_low:
        status = "cancelled"

    # Best dates first: embedded Event JSON-LD (UTC); fall back to
    # rendered text, then the listing card line.
    start = _ld_field(html, "startDate")
    finish = _ld_field(html, "endDate")
    if not start:
        start, finish = _parse_detail_datetime(soup)
    if not start:
        start = _parse_card_datetime(card.get("text", ""))
    if not start:
        return None  # undated: nothing to emit

    venue = ""
    m = re.search(
        r'\\\\"location\\\\":\{\\\\"@type\\\\":\\\\"Place\\\\",'
        r'\\\\"name\\\\":\\\\"([^"\\\\]+)',
        html,
    )
    if not m:  # unescaped variant (flight data already decoded on some pages)
        m = re.search(
            r'"location":\{"@type":"Place","name":"([^"\\]+)', html
        )
    if m:
        venue = _unescape(m.group(1)).strip()
    if not venue or venue == title:
        # Rendered venue anchor (google-maps link) beats echoing title.
        anchor = soup.select_one('a.text-lg[href*="maps.google.com"]')
        if anchor and _text(anchor):
            venue = _text(anchor)
    locality = _ld_field(html, "addressLocality")
    if not venue:
        venue = (card.get("text") or "").split("|")[2].strip() if "|" in card.get("text", "") else ""
    location = venue + (", " + locality if locality and locality not in venue else "")

    description = ""
    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        description = og.get("content").strip()
    if not description:
        paras = sorted(
            (_text(p) for p in soup.find_all("p")),
            key=len, reverse=True,
        )
        description = next((p for p in paras if len(p) > 40), "")
    description = description[:4000]

    price = _ld_field(html, "price")
    cost = price or None
    free = None
    if price and "free" in price.lower():
        free = True
    if re.search(r"(?i)\bfirst visit is free\b", description):
        free = True

    return {
        "name": title,
        "title": title,
        "start": start,
        "finish": finish or None,
        "location": location,
        "description": description,
        "area": location,
        "category": _map_category(card.get("chip", ""), title + " " + description),
        "cost": cost,
        "free": free,
        "source_url": url,
        "status": status,
    }


def _expand_weekly(event: dict) -> list[dict]:
    """Expand an explicit weekly series to dated instances in the window.

    Only fires when the description names the same weekday the dated
    instance falls on (e.g. "every Monday" on a Monday event). Extra
    instances copy the local time forward 7 days at a time.
    """
    try:
        base = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
    except (ValueError, KeyError, TypeError, AttributeError):
        return [event]
    m = _EVERY_WEEKDAY_RE.search(event.get("description") or "")
    if not m or m.group(1).lower() != _WEEKDAYS[base.weekday()]:
        return [event]
    today = datetime.now().date()
    horizon = today + timedelta(days=_WINDOW_DAYS)
    out = [event] if base.date() >= today else []
    nxt = base + timedelta(days=7)
    while nxt.date() < today:
        nxt += timedelta(days=7)
    weeks = 0
    while nxt.date() <= horizon and weeks < _MAX_EXPANSIONS:
        copy = dict(event)
        copy["start"] = nxt.isoformat()
        if event.get("finish"):
            try:
                dur = datetime.fromisoformat(
                    str(event["finish"]).replace("Z", "+00:00")
                ) - base
                copy["finish"] = (nxt + dur).isoformat()
            except ValueError:
                copy["finish"] = None
        copy["description"] = (
            (event.get("description") or "") + " (weekly series)"
        ).strip()[:4000]
        out.append(copy)
        nxt += timedelta(days=7)
        weeks += 1
    if len(out) > 1:
        print(f"[{SOURCE}] expanded weekly series '{event['name']}': {len(out)} instances")
    return out


def fetch() -> list[dict]:
    """Fetch raw community events from balisquad.com.

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
                f"parser assert failed: no /event/<slug-id> links on {LISTING_URL}"
            )
        cards = _collect_card_meta(listing_html)

        events: list[dict] = []
        for index, url in enumerate(links):
            if index:
                time.sleep(1 + random.random())  # 1-2s between page fetches
            detail_html = _get(session, url)
            if not detail_html:
                continue
            try:
                event = _parse_detail(detail_html, url, cards.get(url, {}))
            except Exception as exc:
                print(f"[{SOURCE}] parse failed for {url}: {exc}", file=sys.stderr)
                continue
            if event is None:
                continue
            events.extend(_expand_weekly(event))
        print(f"[{SOURCE}] {len(events)} events from {len(links)} details")
        return events
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"[{SOURCE}] fetch failed: {exc}", file=sys.stderr)
        return []
