"""NOW! Bali events source for the Bali events pipeline.

Scrapes the public month listings at
``https://nowbali.co.id/all-events/?month=<MonthName>`` (current + next
month) plus one detail page per event (``/upcoming-events/<slug>/``).
Exposes ``fetch() -> list[dict]`` of *raw* events; normalization
(uids, UTC times, enums) happens downstream.

Focus is Dining / Arts & Culture (priority) + Wellness (welcome):
each listing/detail article carries an ``event_category-<slug>`` class
(``dining`` -> Food & Drink, ``art-culture``/``festival`` -> Arts &
Culture, ``sports-recreation`` -> Wellness, ``concerts`` -> Music).
Pure-nightlife entries (``event_category-nightlife``) are skipped --
that layer is already covered elsewhere.

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

SOURCE = "now_bali"
TIER = 1

BASE_URL = "https://nowbali.co.id"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://nowbali.co.id)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_DETAIL_RE = re.compile(r"/upcoming-events/[^/]+/?")

# Detail date range: "04 October 2026 - 04 October 2026".
_RANGE_RE = re.compile(
    r"(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+(\d{4})"
    r"\s*-\s*"
    r"(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+(\d{4})"
)
_SINGLE_RE = re.compile(
    r"(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+(\d{4})"
)
# Listing-card date: "October 4, 2026".
_CARD_RE = re.compile(
    r"(January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})"
)
_CAT_CLASS_RE = re.compile(r"event_category-([a-z-]+)")

_EVERY_WEEKDAY_RE = re.compile(
    r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I
)
_WEEKDAYS = (
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
)

# Discovery window for recurrence expansion (today -> +14d).
_WINDOW_DAYS = 14
_MAX_EXPANSIONS = 3

# Article category slugs skipped outright (already-covered layer).
_SKIP_SLUGS = {"nightlife"}

# Article category slug -> canonical raw category (exact enum strings so
# normalize() maps them 1:1; wellness stays Wellness, never Tech).
# Site slugs are coarse (UWRF, a literary festival, sits under
# ``concerts``): literary/exhibition signals in the title win.
_ART_OVERRIDE_RE = re.compile(
    r"writer|literar|book\b|author|poet|exhibition|galler|museum|biennale",
    re.I,
)
_CATEGORY_MAP = {
    "dining": "Food & Drink",
    "art-culture": "Arts & Culture",
    "festival": "Arts & Culture",
    "concerts": "Music",
    "sports-recreation": "Wellness",
    "experience": "Other",
    "business-industry": "Other",
}


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


def _listing_urls() -> list[str]:
    """Month listings for the current + next month (full month names)."""
    today = datetime.now()
    names = []
    for offset in (0, 1):
        month = (today.month - 1 + offset) % 12 + 1
        names.append(datetime(today.year if today.month + offset <= 12 else today.year + 1, month, 1).strftime("%B"))
    return [f"{BASE_URL}/all-events/?month={name}" for name in names]


def _collect_links(html: str) -> list[str]:
    """Dated detail links (``/upcoming-events/<slug>/``) from a listing."""
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=_DETAIL_RE):
        href = (anchor.get("href") or "").split("?")[0].rstrip("/") + "/"
        if "/upcoming-events/" not in href:
            continue
        url = href if href.startswith("http") else BASE_URL + href
        if url in seen:
            continue
        seen.add(url)
        links.append(url)
    return links


def _collect_card_meta(html: str) -> dict[str, dict]:
    """Per-url listing-card facts: category slug, venue, card date line."""
    soup = BeautifulSoup(html, "lxml")
    meta: dict[str, dict] = {}
    for article in soup.find_all("article"):
        link = article.find("a", href=_DETAIL_RE)
        if not link:
            continue
        href = (link.get("href") or "").split("?")[0].rstrip("/") + "/"
        if "/upcoming-events/" not in href:
            continue
        url = href if href.startswith("http") else BASE_URL + href
        slug = ""
        for cls in article.get("class", []) or []:
            m = _CAT_CLASS_RE.match(cls)
            if m:
                slug = m.group(1)
                break
        venue = ""
        loc = article.select_one("div.location")
        if loc:
            venue = _text(loc)
        card_date = ""
        date_div = article.select_one("div.pt-2.pb-4")
        if date_div:
            card_date = _text(date_div)
        meta[url] = {"slug": slug, "venue": venue, "card_date": card_date}
    return meta


def _iso_day(day: str, month: str, year: str) -> str:
    """'4', 'October', '2026' -> '2026-10-04' ('' on miss)."""
    try:
        return datetime.strptime(
            "%s %s, %s" % (month, day, year), "%B %d, %Y"
        ).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _card_iso(text: str) -> str:
    """'October 4, 2026' -> '2026-10-04' ('' on miss)."""
    m = _CARD_RE.search(text or "")
    if not m:
        return ""
    return _iso_day(m.group(2), m.group(1), m.group(3))


def _parse_detail(html: str, url: str, card: dict) -> dict | None:
    """Build a raw event dict from an event detail page (None = skip)."""
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    title = _text(h1)
    if not title:
        return None

    slug = ""
    article = soup.find("article")
    if article is not None:
        for cls in article.get("class", []) or []:
            m = _CAT_CLASS_RE.match(cls)
            if m:
                slug = m.group(1)
                break
    slug = slug or card.get("slug", "")
    if slug in _SKIP_SLUGS:
        return None  # pure nightlife: already covered, skip
    category = _CATEGORY_MAP.get(slug, "Other")
    if category == "Music" and _ART_OVERRIDE_RE.search(title):
        category = "Arts & Culture"

    # Date range block: "04 October 2026 - 04 October 2026".
    start, finish = "", ""
    entry = soup.select_one("div.post-entry")
    scope = _text(entry) if entry else soup.get_text(" ", strip=True)
    m = _RANGE_RE.search(scope)
    if m:
        start = _iso_day(m.group(1), m.group(2), m.group(3))
        end = _iso_day(m.group(4), m.group(5), m.group(6))
        if end and end != start:
            finish = end
    else:
        m = _SINGLE_RE.search(scope)
        if m:
            start = _iso_day(m.group(1), m.group(2), m.group(3))
    if not start:
        start = _card_iso(card.get("card_date", ""))
    if not start:
        return None  # undated: nothing to emit

    venue = ""
    if entry is not None:
        venue_div = entry.select_one("div.pb-3.fs-6")
        if venue_div:
            venue = _text(venue_div)
    location = venue or card.get("venue", "")

    description = ""
    if entry is not None:
        paras = [_text(p) for p in entry.find_all("p")]
        paras = [p for p in paras if p]
        description = " ".join(paras[:3])[:4000]

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
        "cost": None,
        "free": None,
        "source_url": url,
        "status": status,
    }


def _expand_weekly(event: dict) -> list[dict]:
    """Expand an explicit weekly series to dated instances in the window.

    Only fires when the description names the same weekday the dated
    instance falls on (e.g. "every Thursday" on a Thursday event).
    Extra instances copy the date forward 7 days at a time.
    """
    try:
        base = datetime.fromisoformat(str(event["start"]))
    except (ValueError, KeyError, TypeError):
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
        copy["start"] = nxt.strftime("%Y-%m-%d")
        if event.get("finish"):
            try:
                dur = datetime.fromisoformat(str(event["finish"])) - base
                copy["finish"] = (nxt + dur).strftime("%Y-%m-%d")
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
    """Fetch raw dining/culture/wellness events from nowbali.co.id.

    Returns a list of dicts (possibly empty). Raises RuntimeError when
    the listings yield zero dated links (parser assert: a redesign
    pages us instead of silently emptying the feed); per-page failures
    are logged and skipped.
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        listing_urls = _listing_urls()
        links: list[str] = []
        seen: set[str] = set()
        cards: dict[str, dict] = {}
        for listing_url in listing_urls:
            html = _get(session, listing_url)
            if not html:
                continue
            time.sleep(1 + random.random())  # 1-2s politeness sleep
            for url in _collect_links(html):
                if url not in seen:
                    seen.add(url)
                    links.append(url)
            cards.update(_collect_card_meta(html))
        if not links:
            raise RuntimeError(
                f"parser assert failed: no /upcoming-events/ links on {listing_urls}"
            )

        events: list[dict] = []
        skipped_nightlife = 0
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
