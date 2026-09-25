"""Honeycombers Bali calendar source for the Bali events pipeline.

Scrapes the public listings at https://thehoneycombers.com/bali/calendar/
(+ /this-week/, /this-month/) plus one detail page per event
(``/bali/event/<slug>/``). Exposes ``fetch() -> list[dict]`` of *raw*
events; normalization (uids, UTC times, enums) happens downstream.

Focus is NON-nightlife (Music, Food & Drink, Arts & Culture, Wellness,
Surf, Coworking & Tech): detail pages carry an ``.event-category`` label
and schema.org ``meta[itemprop=startDate/endDate]`` datetimes plus a
scoped ``[itemprop=location]`` block (venue name + street address).
Events whose category is pure nightlife are skipped (that layer is
already covered); cross-category labels such as "Music and Nightlife"
are kept under the non-nightlife side.

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

SOURCE = "honeycombers"
TIER = 2

BASE_URL = "https://thehoneycombers.com"
LISTING_URLS = [
    BASE_URL + "/bali/calendar/",
    BASE_URL + "/bali/calendar/this-week/",
    BASE_URL + "/bali/calendar/this-month/",
]
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://thehoneycombers.com)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# meta[itemprop=startDate] looks like "2026-09-24T05:00 pm+08:00".
_START_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})T(\d{1,2}):(\d{2})\s*([AaPp])[Mm]\s*([+-]\d{2}):?(\d{2})?"
)

_WEEKDAYS = (
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
)
_EVERY_WEEKDAY_RE = re.compile(
    r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I
)

# Discovery window for recurrence expansion (today -> +14d).
_WINDOW_DAYS = 14
_MAX_EXPANSIONS = 3


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
    """Dated detail links (``/bali/event/<slug>/``) from a listing page."""
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=re.compile(r"/bali/event/[^/]+/?")):
        href = (anchor.get("href") or "").split("?")[0].rstrip("/") + "/"
        if "/bali/event/" not in href:
            continue
        url = href if href.startswith("http") else BASE_URL + href
        if url in seen:
            continue
        seen.add(url)
        links.append(url)
    return links


def _parse_schema_dt(raw: str) -> str:
    """'2026-09-24T05:00 pm+08:00' -> '2026-09-24 17:00+08:00' ('' on miss)."""
    m = _START_RE.search(raw or "")
    if not m:
        return ""
    day, hour, minute, ampm, off_h, off_m = m.groups()
    hour = int(hour) % 12 + (12 if ampm.upper() == "P" else 0)
    return f"{day} {hour:02d}:{minute}{off_h}:{off_m or '00'}"


def _map_category(label: str) -> str | None:
    """Map an ``.event-category`` label to a raw category, or None to skip.

    Pure-nightlife labels return None (already covered elsewhere);
    cross-category labels keep the non-nightlife side.
    """
    low = (label or "").lower()
    has_night = "nightlife" in low or "night life" in low
    if "wellness" in low or "yoga" in low or "retreat" in low or "spa" in low:
        return "wellness"
    if "food" in low or "drink" in low or "dining" in low or "restaurant" in low:
        return "food"
    if (
        "art" in low
        or "cultur" in low
        or "exhibition" in low
        or "gallery" in low
        or "theatr" in low
        or "craft" in low
        or "market" in low
    ):
        return "art"
    if "music" in low or "concert" in low or "gig" in low:
        return "music"
    if "surf" in low or "sport" in low or "fitness" in low:
        return "sport"
    if "tech" in low or "coworking" in low or "startup" in low:
        return "tech"
    if "communit" in low:
        return "community"
    if has_night or "party" in low or "club" in low or "dj" in low:
        return None  # pure nightlife: covered elsewhere, skip
    return "other"


def _parse_detail(html: str, url: str) -> dict | None:
    """Build a raw event dict from an event detail page (None = skip)."""
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    title = _text(h1)
    if not title:
        meta_name = soup.find("meta", attrs={"itemprop": "name"})
        title = ((meta_name.get("content") or "").strip() if meta_name else "")
    if not title and soup.title:
        title = _text(soup.title).split("|")[0].strip()
    if not title:
        return None

    cat_label = ""
    cat_node = soup.select_one(".event-category")
    if cat_node:
        cat_label = _text(cat_node)
    category = _map_category(cat_label)
    if category is None:
        return None  # pure nightlife: out of focus

    start = ""
    finish = ""
    for meta in soup.find_all("meta", itemprop=True):
        prop = (meta.get("itemprop") or "").strip()
        if prop == "startDate" and not start:
            start = _parse_schema_dt(meta.get("content") or "")
        elif prop == "endDate" and not finish:
            finish = _parse_schema_dt(meta.get("content") or "")
    if not start:
        return None  # undated: nothing to emit

    description = ""
    meta_desc = soup.find("meta", attrs={"itemprop": "description"})
    if meta_desc and meta_desc.get("content"):
        description = meta_desc.get("content").strip()
    description = description[:4000]

    try:
        start_dt = datetime.fromisoformat(start)
    except ValueError:
        return None
    start_day = start_dt.date()
    if finish:
        try:
            if datetime.fromisoformat(finish) <= start_dt:
                # Same-evening editorial quirk ("5pm-12pm"): roll past midnight.
                if datetime.fromisoformat(finish).date() == start_day:
                    finish = (
                        datetime.fromisoformat(finish) + timedelta(days=1)
                    ).isoformat()
                else:
                    finish = ""  # sloppy editorial endDate: drop, don't invert
        except ValueError:
            finish = ""
    if not finish:
        # Multi-day exhibitions/promos render a range block
        # ("Dates & Time 09 Sep - 09 Dec 2026 ..."); use the range end
        # as the finish date so window overlap keeps them visible.
        page_text = soup.get_text(" ", strip=True)
        m_end = re.search(
            r"(\d{1,2})\s+"
            r"(January|February|March|April|May|June|July|"
            r"August|September|October|November|December)"
            r"\s*-\s*(\d{1,2})\s+"
            r"(January|February|March|April|May|June|July|"
            r"August|September|October|November|December)\s+(\d{4})",
            page_text,
        )
        if m_end:
            try:
                end_day = datetime.strptime(
                    "%s %s, %s" % (m_end.group(4), m_end.group(3), m_end.group(5)),
                    "%B %d, %Y",
                )
                if end_day.date() >= start_day:
                    finish = end_day.replace(hour=18).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass

    venue, address = "", ""
    loc = soup.find(attrs={"itemprop": "location"})
    if loc is not None:
        name_node = loc.find(attrs={"itemprop": "name"})
        addr_node = loc.find(attrs={"itemprop": "address"})
        venue = _text(name_node)
        address = _text(addr_node)
        if not venue and not address:
            whole = _text(loc)
            if "|" in whole:
                venue, address = [p.strip() for p in whole.split("|", 1)]
            else:
                venue = whole
    location = venue + (", " + address if address else "")

    cost = None
    free = None
    price_node = soup.find(attrs={"itemprop": "price"})
    price = _text(price_node)
    if price and price not in ("--", "-"):
        cost = price
        if "free" in price.lower():
            free = True

    status = "confirmed"
    if "cancelled" in f"{title} {description}".lower():
        status = "cancelled"

    return {
        "name": title,
        "title": title,
        "start": start,
        "finish": finish or None,
        "location": location,
        "description": description,
        "area": location,
        "category": category,
        "cost": cost,
        "free": free,
        "source_url": url,
        "status": status,
    }


def _expand_weekly(event: dict) -> list[dict]:
    """Expand an explicit weekly series to dated instances in the window.

    Only fires when the description names the same weekday the dated
    instance falls on (e.g. "every Thursday" on a Thursday event).
    Extra instances copy the local time forward 7 days at a time.
    """
    try:
        base = datetime.fromisoformat(event["start"])
    except (ValueError, KeyError, TypeError):
        return [event]
    m = _EVERY_WEEKDAY_RE.search(event.get("description") or "")
    if not m or m.group(1).lower() != _WEEKDAYS[base.weekday()]:
        return [event]
    today = datetime.now().date()
    horizon = today + timedelta(days=_WINDOW_DAYS)
    # Only expand forward: a stale dated instance (base before today)
    # contributes its next in-window occurrences, never past ones.
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
                dur = datetime.fromisoformat(event["finish"]) - base
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
    """Fetch raw non-nightlife events from thehoneycombers.com.

    Returns a list of dicts (possibly empty). Raises RuntimeError when
    the listings yield zero dated links (parser assert: a redesign
    pages us instead of silently emptying the feed); per-page failures
    are logged and skipped.
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        links: list[str] = []
        seen: set[str] = set()
        for listing_url in LISTING_URLS:
            html = _get(session, listing_url)
            if not html:
                continue
            time.sleep(1 + random.random())  # 1-2s politeness sleep
            for url in _collect_links(html):
                if url not in seen:
                    seen.add(url)
                    links.append(url)
        if not links:
            raise RuntimeError(f"parser assert failed: no /bali/event/ links on {LISTING_URLS}")

        events: list[dict] = []
        skipped_nightlife = 0
        for index, url in enumerate(links):
            if index:
                time.sleep(1 + random.random())  # 1-2s between page fetches
            detail_html = _get(session, url)
            if not detail_html:
                continue
            try:
                event = _parse_detail(detail_html, url)
            except Exception as exc:
                print(f"[{SOURCE}] parse failed for {url}: {exc}", file=sys.stderr)
                continue
            if event is None:
                skipped_nightlife += 1
                continue
            events.extend(_expand_weekly(event))
        print(
            f"[{SOURCE}] {len(events)} events from {len(links)} details "
            f"({skipped_nightlife} nightlife/undated skipped)"
        )
        return events
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"[{SOURCE}] fetch failed: {exc}", file=sys.stderr)
        return []
