"""BitcoinOnly Events (Bitcoin Indonesia hub) source for the Bali pipeline.

Scrapes the server-rendered hub page
``https://bitcoinonly.events/bitcoin-indonesia/`` (``div.upcoming_group_event``
blocks: title + detail link + ``Date: Fri, Oct 9, 2026`` + ``Time: 05:00 PM
-- 07:00 PM / (UTC +08:00) WITA (Bali)`` + venue line) plus one detail page
per event (``Date:``/``Time:``/``Location:``/``Website:`` fields). Exposes
``fetch() -> list[dict]`` of *raw* events; normalization (uids, UTC times,
enums) happens downstream.

Verified 2026-10-06: hub returns HTTP 200 with plain GET (no login, no JS,
no bot wall). Upcoming list names the Canggu tech anchor (Bitcoin House
Bali, Jalan Kayu Manis, Kuta Utara, Canggu) with WITA times; past-event
archive proves cadence. Same-origin cluster as bitcoinindonesia.xyz
(detail ``Website:`` links point there) -- treat as one origin for
corroboration, never double-confirm across them.

Only Bali-venue events are kept (Canggu/Ubud/Denpasar/Kuta/Badung);
Jakarta/Bandung/Surabaya hub entries are out of scope.

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

SOURCE = "bitcoinonly"
TIER = 2

BASE_URL = "https://bitcoinonly.events"
LISTING_URL = BASE_URL + "/bitcoin-indonesia/"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://bitcoinonly.events/bitcoin-indonesia/)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Discovery window: only dated instances inside today -> +14d are emitted.
_WINDOW_DAYS = 14

# Listing date line: "Date: Fri, Oct 9, 2026".
_DATE_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2}),?\s+(\d{4})",
    re.I,
)
# Listing time line: "Time: 05:00 PM -- 07:00 PM / (UTC +08:00) WITA (Bali)".
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?", re.I)

# Bali-scope venue filter: hub covers all Indonesia, we keep Bali-island only.
_BALI_RES = (
    "bali", "canggu", "ubud", "denpasar", "kuta", "badung", "gianyar",
    "pererenan", "berawa", "tumbak bayuh", "uluwatu", "seminyak",
    "kerobokan", "tabanan", "seseh", "munggu", "echo beach", "batu bolong",
    "kayu manis",
)


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


def _parse_listing_date(text: str) -> tuple[int, int, int] | None:
    """'Date: Fri, Oct 9, 2026' -> (year, month, day) (None on miss)."""
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    try:
        month = datetime.strptime(m.group(1)[:3], "%b").month
        return (int(m.group(3)), month, int(m.group(2)))
    except ValueError:
        return None


def _parse_listing_time(text: str) -> tuple[int, int] | None:
    """First 'HH:MM PM' in a Time line -> (hour24, minute) (None on miss)."""
    m = _TIME_RE.search(text or "")
    if not m:
        return None
    try:
        hour = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "P" else 0)
        return (hour, int(m.group(2) or 0))
    except ValueError:
        return None


def _collect_upcoming(html: str) -> list[dict]:
    """Upcoming blocks: detail url + title/date/time/venue/description."""
    soup = BeautifulSoup(html, "lxml")
    cards: list[dict] = []
    seen: set[str] = set()
    for block in soup.select("div.upcoming_group_event"):
        anchor = block.select_one("h3 a[href]")
        if anchor is None:
            continue
        href = (anchor.get("href") or "").split("?")[0]
        url = href if href.startswith("http") else BASE_URL + href
        if url in seen:
            continue
        seen.add(url)
        cards.append({
            "url": url,
            "title": _text(anchor),
            "date": _text(block.select_one("p.single_group_event_date")),
            "time": _text(block.select_one("p.single_group_event_time")),
            "venue": _text(block.select_one("p.single_group_event_location")),
            "description": _text(block.select_one("p.single_group_event_decription")),
        })
    return cards


def _parse_detail(html: str, url: str, card: dict) -> dict | None:
    """Build a raw event dict from a detail page + listing card."""
    soup = BeautifulSoup(html, "lxml")
    body = soup.get_text(" ", strip=True)

    title = card.get("title", "")
    h1 = soup.find("h1")
    if h1 and _text(h1):
        title = _text(h1)
    if not title:
        return None

    # Date: listing card first (upcoming = next occurrence); detail
    # "Date: Wed, Oct 21, 2026" corroborates -- mismatch means skip.
    ymd = _parse_listing_date(card.get("date", ""))
    if ymd is None:
        return None
    detail_dates = _DATE_RE.findall(body)
    corroborated = any(
        int(d[2]) == ymd[0]
        and datetime.strptime(d[0][:3], "%b").month == ymd[1]
        and int(d[1]) == ymd[2]
        for d in detail_dates
        if len(d) == 3
    ) if detail_dates else True
    if detail_dates and not corroborated:
        print(f"[{SOURCE}] date mismatch card vs detail: {url}",
              file=sys.stderr)
        return None

    # Time-of-day from the listing Time line (WITA = UTC+8, normalize input).
    hm = _parse_listing_time(card.get("time", ""))
    hour, minute = hm if hm else (18, 0)
    try:
        start = datetime(ymd[0], ymd[1], ymd[2], hour, minute).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None

    # Venue: listing location line; must name a Bali venue (hoax-check:
    # never invent a Canggu venue string, never emit Java/Sulawesi rows).
    venue = card.get("venue", "")
    if not venue:
        m = re.search(r"Location:\s*([^|]{4,120}?)(?:\s{2,}|Website:|$)", body)
        venue = _text(m.group(1)) if m else ""
    if not venue or not any(k in venue.lower() for k in _BALI_RES):
        print(f"[{SOURCE}] skipping non-Bali venue: {url}", file=sys.stderr)
        return None

    # Discovery window: today -> +14d only.
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    today = datetime.now().date()
    horizon = today + timedelta(days=_WINDOW_DAYS)
    if not (today <= start_dt.date() <= horizon):
        return None

    # Organizer: detail Website link host (bitcoinindonesia.xyz cluster)
    # or explicit organizer credit; defaults to the hub curator.
    organizer = "Bitcoin Indonesia"
    if "bitcoinindonesia.xyz" not in body.lower():
        om = re.search(r"[Oo]rganiz(?:er|ed by|er:?)\s+([A-Z][^|.(]{2,60})", body)
        if om:
            organizer = _text(om.group(1))

    description = card.get("description", "")
    if organizer and organizer.lower() not in description.lower():
        description = (description + f" (Organizer: {organizer})").strip()
    description = description[:4000]

    return {
        "name": title,
        "title": title,
        "start": start,
        "finish": None,
        "location": venue,
        "description": description,
        "area": venue,
        "category": "tech",
        "cost": None,
        "free": "free" in description.lower() or None,
        "source_url": url,
        "status": "confirmed",
    }


def fetch() -> list[dict]:
    """Fetch raw Bali bitcoin/tech events from bitcoinonly.events.

    Returns a list of dicts (possibly empty). Raises RuntimeError when
    the hub yields zero dated upcoming blocks (parser assert: a redesign
    pages us instead of silently emptying the feed); per-page failures
    are logged and skipped.
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        listing_html = _get(session, LISTING_URL)
        if not listing_html:
            return []
        cards = _collect_upcoming(listing_html)
        if not cards:
            raise RuntimeError(
                f"parser assert failed: no upcoming blocks on {LISTING_URL}"
            )

        events: list[dict] = []
        for index, card in enumerate(cards):
            if index:
                time.sleep(1 + random.random())  # 1-2s between page fetches
            detail_html = _get(session, card["url"])
            if not detail_html:
                continue
            try:
                event = _parse_detail(detail_html, card["url"], card)
            except Exception as exc:
                print(f"[{SOURCE}] parse failed for {card['url']}: {exc}",
                      file=sys.stderr)
                continue
            if event is None:
                continue
            events.append(event)
        print(f"[{SOURCE}] {len(events)} events from {len(cards)} upcoming")
        if not events:
            raise RuntimeError(
                f"parser assert failed: no dated links on {LISTING_URL}"
            )
        return events
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"[{SOURCE}] fetch failed: {exc}", file=sys.stderr)
        return []
