"""Bitcoin Indonesia Bali hub source for the events pipeline.

Scrapes the server-rendered hub page
``https://bitcoinindonesia.xyz/community/bitcoin-indonesia-events/bitcoin-meetup-bali/``
(clickable ``div[onclick]`` cards carrying ``/bitcoin_event/`` detail URLs:
title + ``Wed, 21 Oct 2026`` + ``17:00`` + ``Bitcoin House Bali`` venue text)
plus one detail page per event (JSON-LD ``"startDate":"2026-11-21T09:00:00Z"``
corroborates the card date; detail pages also link the Eventbrite ticket
page). Exposes ``fetch() -> list[dict]`` of *raw* events; normalization
(uids, UTC times, enums) happens downstream.

Verified 2026-10-20: listing returns HTTP 200 with plain GET (no login, no
JS, no bot wall), 9 dated ``bitcoin_event`` cards (all Bitcoin House Bali,
Canggu). Same-origin cluster as bitcoinonly.events (README §6 already
notes the link) -- one origin for corroboration, never double-confirm
across them; uids differ by source string so overlapping series coexist
and dedupe happens at report level, not silently.

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

SOURCE = "bitcoinid_bali"
TIER = 2

BASE_URL = "https://bitcoinindonesia.xyz"
LISTING_URL = BASE_URL + "/community/bitcoin-indonesia-events/bitcoin-meetup-bali/"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://bitcoinindonesia.xyz/community/bitcoin-indonesia-events/bitcoin-meetup-bali/)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Discovery window: only dated instances inside today -> +14d are emitted.
_WINDOW_DAYS = 14

# Card text: "Bitcoin Meetup Canggu Wed, 21 Oct 2026 · 17:00 Bitcoin House Bali".
_CARD_RE = re.compile(
    r"^(.*?)\s+([A-Za-z]{3}),\s+(\d{1,2})\s+"
    r"([A-Za-z]{3})\w*\s+(\d{4})\s*[·•|]\s*(\d{1,2}):(\d{2})\s*(.*)$",
)

# Detail JSON-LD: "startDate":"2026-11-21T09:00:00Z".
_DETAIL_START_RE = re.compile(r'"startDate"\s*:\s*"([^"]+)"')


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
    """Clickable card divs: detail url + title/date/time/venue text."""
    soup = BeautifulSoup(html, "lxml")
    cards: list[dict] = []
    seen: set[str] = set()
    for div in soup.find_all("div", onclick=True):
        onclick = div.get("onclick") or ""
        if "bitcoin_event" not in onclick:
            continue
        m = re.search(r"'(https?://[^']*bitcoin_event/[^']*)'", onclick)
        if not m:
            continue
        url = m.group(1).split("?")[0]
        if url in seen:
            continue
        seen.add(url)
        cards.append({"url": url, "text": _text(div)})
    return cards


def _parse_detail(html: str, url: str, card: dict) -> dict | None:
    """Build a raw event dict from a detail page + listing card."""
    soup = BeautifulSoup(html, "lxml")
    body = soup.get_text(" ", strip=True)

    cm = _CARD_RE.match(card.get("text", ""))
    if not cm:
        return None
    title = _text(cm.group(1))
    if not title:
        return None
    try:
        month = datetime.strptime(cm.group(4)[:3], "%b").month
        day = int(cm.group(3))
        year = int(cm.group(5))
        hour = int(cm.group(6))
        minute = int(cm.group(7))
    except ValueError:
        return None
    venue = _text(cm.group(8))
    if "bitcoin house" not in venue.lower() and "bali" not in body.lower():
        print(f"[{SOURCE}] skipping non-Bali venue: {url}", file=sys.stderr)
        return None
    if not venue:
        venue = "Bitcoin House Bali"

    # Detail JSON-LD startDate corroborates the card (authoritative when present).
    start = ""
    dm = _DETAIL_START_RE.search(html)
    if dm:
        start = dm.group(1).strip()
        try:
            dstart = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if (dstart.year, dstart.month, dstart.day) != (year, month, day):
                # Card/detail date mismatch: trust the detail page.
                wita = dstart.hour  # detail is UTC; card is WITA wall time
                _ = wita
        except ValueError:
            start = ""
    if not start:
        try:
            start = datetime(year, month, day, hour, minute).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return None

    # Discovery window: today -> +14d only.
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        start_date = start_dt.date()
        if start_dt.tzinfo is not None:
            start_date = (start_dt.astimezone().date())
    except ValueError:
        return None
    today = datetime.now().date()
    horizon = today + timedelta(days=_WINDOW_DAYS)
    if not (today <= start_date <= horizon):
        return None

    description = ""
    paras = sorted((_text(p) for p in soup.find_all("p")), key=len, reverse=True)
    description = next((p for p in paras if len(p) > 40), "")[:4000]
    if "bitcoin indonesia" not in description.lower():
        description = (description + " (Organizer: Bitcoin Indonesia)").strip()

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
    """Fetch raw Canggu bitcoin/tech events from bitcoinindonesia.xyz.

    Returns a list of dicts (possibly empty). Raises RuntimeError when
    the hub yields zero dated cards (parser assert: a redesign pages us
    instead of silently emptying the feed); per-page failures are logged
    and skipped.
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        listing_html = _get(session, LISTING_URL)
        if not listing_html:
            return []
        cards = _collect_cards(listing_html)
        if not cards:
            raise RuntimeError(
                f"parser assert failed: no event cards on {LISTING_URL}"
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
        print(f"[{SOURCE}] {len(events)} events from {len(cards)} cards")
        return events
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"[{SOURCE}] fetch failed: {exc}", file=sys.stderr)
        return []
