"""Bali Startup & Tech Community (BSTC) source for the Bali pipeline.

Scrapes the server-rendered listing
``https://www.balistartupandtech.com/events`` (``a[href^="/events/"]``
cards: title + description + ``<span>`` date line
``"Wednesday, November 4, 2026"`` + venue span
``"Seoul Soul Project, Canggu"``) plus one detail page per event
(``/events/<slug>``: full date + time ``"Thursday, November 12,
2026, 18:30 WITA"`` + venue + RSVP info + JSON-LD). Exposes
``fetch() -> list[dict]`` of *raw* events; normalization (uids, UTC
times, enums) happens downstream.

Verified 2026-10-26: listing returns HTTP 200 with plain GET (no
login, no JS, no bot wall); ~20 dated ``/events/<slug>`` links, all
Canggu tech (How I AI / Builder Sessions / networking dinners at
Seoul Soul Project + Yema Kitchen). Aggregation overlap: BSTC RSVPs
via meetup.com/bali-start-ups-tech-community (already covered by
meetup.py) -- merge dedupes on content.

Only dated events inside the discovery window (today -> +14d) are
emitted; past events (earlier 2026 series) are skipped, vague
venues rejected per hoax-check rules.

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

SOURCE = "bstc"
TIER = 2

BASE_URL = "https://www.balistartupandtech.com"
LISTING_URL = BASE_URL + "/events"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://www.balistartupandtech.com/events)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Discovery window: only dated instances inside today -> +14d are emitted.
_WINDOW_DAYS = 14

_EVENT_HREF_RE = re.compile(r"^/events/[a-z0-9][a-z0-9-]+/?$", re.I)

# Listing/detail date: "Wednesday, November 4, 2026" (+ optional time).
_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{1,2}),?\s+(20\d\d)",
    re.I,
)
# Detail time: "18:30 WITA" or "6:30 pm". An explicit "Doors open
# HH:MM" line in the schedule is NOT the start -- prefer the header
# "Date ... HH:MM WITA" line that sits next to the venue.
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(WITA|[AP])\.?M?\.?", re.I)

# Canggu-scope guard: BSTC is Canggu-first, but reject anything that
# does not name a Bali venue (hoax-check: never emit vague rows).
_BALI_RES = (
    "bali", "canggu", "pererenan", "berawa", "tumbak bayuh",
    "batu bolong", "echo beach", "seseh", "munggu", "kerobokan",
    "seminyak", "kuta", "ubud", "denpasar", "tabanan", "sanur",
    "yema kitchen", "seoul soul project",
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


def _collect_cards(html: str) -> list[dict]:
    """Listing cards: /events/<slug> anchors + title/date/venue spans.

    Only Upcoming cards are collected; Past Event cards are skipped
    (their dates are months old and outside the discovery window).
    """
    soup = BeautifulSoup(html, "lxml")
    cards: list[dict] = []
    seen: set[str] = set()
    for anchor in soup.select('a[href^="/events/"]'):
        href = (anchor.get("href") or "").split("?")[0].rstrip("/") or "/"
        if not _EVENT_HREF_RE.match(href):
            continue
        url = BASE_URL + href
        if url in seen:
            continue
        seen.add(url)
        card_text = _text(anchor)
        if re.search(r"\bPast Event\b", card_text):
            continue
        date_m = _DATE_RE.search(card_text)
        cards.append({
            "url": url,
            "title": _text(anchor.find(["h1", "h2", "h3"]))
            or card_text[:120],
            "date": date_m.group(0) if date_m else "",
            "card": card_text,
        })
    return cards


def _parse_detail(html: str, url: str, card: dict) -> dict | None:
    """Build a raw event dict from a detail page + listing card."""
    soup = BeautifulSoup(html, "lxml")
    body = soup.get_text(" ", strip=True)

    title = ""
    h1 = soup.find("h1")
    if h1 and _text(h1):
        title = _text(h1)
    if not title:
        m = re.search(r'"name"\s*:\s*"([^"]{4,150})"', html)
        title = m.group(1).strip() if m else ""
    if not title:
        title = card.get("title", "")
    if not title:
        return None

    # Date: detail full line first ("Thursday, November 12, 2026");
    # listing card date corroborates.
    ymd = None
    for source_text in (body, card.get("card", "")):
        m = _DATE_RE.search(source_text or "")
        if m:
            try:
                month = datetime.strptime(m.group(1)[:3], "%b").month
                ymd = (int(m.group(3)), month, int(m.group(2)))
                break
            except ValueError:
                continue
    if ymd is None:
        print(f"[{SOURCE}] skipping undated event: {url}", file=sys.stderr)
        return None

    # Time-of-day: detail header line "November 12, 2026 18:30 WITA"
    # (date + time + WITA together next to the venue) is authoritative.
    # Fall back to a bare "HH:MM WITA" elsewhere; never take a "Doors
    # open HH:MM" schedule line (that is doors, not start).
    hour, minute = 18, 30
    tm = re.search(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+20\d\d\s+"
        r"(\d{1,2}):(\d{2})\s*WITA",
        body, re.I,
    )
    if tm:
        try:
            hour, minute = int(tm.group(2)), int(tm.group(3))
        except ValueError:
            pass
    else:
        tm2 = _TIME_RE.search(body)
        if tm2:
            try:
                h, mi = int(tm2.group(1)), int(tm2.group(2))
                suffix = (tm2.group(3) or "").upper()
                if suffix == "WITA":
                    hour, minute = h, mi
                elif suffix == "P":
                    hour, minute = h % 12 + 12, mi
                elif suffix == "A":
                    hour, minute = h % 12, mi
                else:
                    hour, minute = h, mi
            except ValueError:
                pass
    try:
        start = datetime(ymd[0], ymd[1], ymd[2], hour, minute).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None

    # Venue: detail text, must name a Bali venue (hoax-check).
    # Prefer the JSON-LD location name when present (exact venue).
    venue = ""
    ld = re.search(r'"location"\s*:\s*\{[^}]{0,400}?"name"\s*:\s*"([^"]{4,120})"', html)
    if ld:
        venue = _text(ld.group(1))
    if not venue:
        m = re.search(
            r"((?:Seoul Soul Project|Yema Kitchen)[^|]{0,60}|"
            r"[A-Z][^|]{3,80}(?:Canggu|Pererenan|Berawa|Bali)[^|]{0,80})",
            body,
        )
        if m:
            venue = _text(m.group(1))
    if not venue or not any(k in venue.lower() for k in _BALI_RES):
        print(f"[{SOURCE}] skipping vague/non-Bali venue: {url}", file=sys.stderr)
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

    description = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        description = _text(str(meta.get("content")))
    if not description:
        paras = [_text(p) for p in soup.find_all("p")]
        description = next((p for p in paras if len(p) > 40), paras[0] if paras else "")
    if "meetup.com" in html.lower():
        description = (description + " (RSVP via Meetup group.)").strip()
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
    """Fetch raw Canggu tech events from balistartupandtech.com.

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
        cards = [c for c in _collect_cards(listing_html) if c.get("date")]
        if not cards:
            raise RuntimeError(
                f"parser assert failed: no dated /events/<slug> links on {LISTING_URL}"
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
        upcoming = len(cards)
        print(f"[{SOURCE}] {len(events)} in-window events from {upcoming} upcoming cards")
        if not events:
            # Cards parsed fine but every event fell outside today ->
            # +14d (e.g. only future-dated-next-month rows). Quiet
            # fortnight: return [] so the orchestrator keeps last-good.
            print(f"[{SOURCE}] 0 in-window events from {upcoming} "
                  f"upcoming (outside today -> +14d); returning []")
            return []
        return events
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"[{SOURCE}] fetch failed: {exc}", file=sys.stderr)
        return []
