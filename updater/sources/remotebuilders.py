"""Remote Builders Canggu tech/community source for the Bali pipeline.

Scrapes the server-rendered listing ``https://remotebuilders.io/events/``
(``script[type=application/ld+json]`` schema.org Event blocks: name +
``startDate``/``endDate`` with +08:00 + ``location`` name/addressLocality
+ ``offers.url`` Luma RSVP link). Exposes ``fetch() -> list[dict]`` of
*raw* events; normalization (uids, UTC times, enums) happens downstream.

Verified 2026-10-29: listing returns HTTP 200 with plain GET (no login,
no JS, no bot wall; static HTML ~20 KB, 2 JSON-LD Event blocks). Canggu
tech anchor events (How I AI @ Seoul Soul Project, BSTC networking
dinners @ Yema Kitchen) with WITA datetimes. Aggregation layer (upstream
Luma booking URLs kept in description) -- dedupe via merge, corroboration
only vs bstc.py/meetup.py coverage of the same series.

Only dated events inside the discovery window (today -> +14d) are
emitted; vague/non-Canggu venues rejected per hoax-check rules.

requests + beautifulsoup only. No browser, no login, no JS.
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

SOURCE = "remotebuilders"
TIER = 2

BASE_URL = "https://remotebuilders.io"
LISTING_URL = BASE_URL + "/events/"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://remotebuilders.io/events/)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Discovery window: only dated instances inside today -> +14d are emitted.
_WINDOW_DAYS = 14

# Canggu-scope guard: keep rows naming a Bali venue (hoax-check).
_BALI_RES = (
    "bali", "canggu", "pererenan", "berawa", "tumbak bayuh",
    "batu bolong", "echo beach", "seseh", "munggu", "kerobokan",
    "seminyak", "kuta", "ubud", "denpasar", "tabanan", "sanur",
    "denpasar", "yema kitchen", "seoul soul project",
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


def _collect_blocks(html: str) -> list[dict]:
    """JSON-LD Event blocks on the listing page."""
    soup = BeautifulSoup(html, "lxml")
    blocks: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw or '"@type"' not in raw or "Event" not in raw:
            continue
        try:
            payload = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "Event":
                blocks.append(item)
    return blocks


def _parse_block(block: dict) -> dict | None:
    """Build a raw event dict from one JSON-LD Event block."""
    title = _text(block.get("name", ""))
    if not title:
        return None

    start_raw = str(block.get("startDate", "") or "").strip()
    if not start_raw:
        return None
    try:
        start_dt = datetime.fromisoformat(start_raw)
    except ValueError:
        return None
    if start_dt.tzinfo is None:
        # WITA = UTC+8 (organizer-local, stated on page).
        start_dt = start_dt.replace(tzinfo=timezone(timedelta(hours=8)))
    start = start_dt.strftime("%Y-%m-%d %H:%M")

    finish = None
    end_raw = str(block.get("endDate", "") or "").strip()
    if end_raw:
        try:
            end_dt = datetime.fromisoformat(end_raw)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone(timedelta(hours=8)))
            finish = end_dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            finish = None

    loc = block.get("location") or {}
    venue = _text(loc.get("name", "")) if isinstance(loc, dict) else ""
    addr = loc.get("address", {}) if isinstance(loc, dict) else {}
    locality = _text(addr.get("addressLocality", "")) if isinstance(addr, dict) else ""
    venue_full = f"{venue}, {locality}" if locality and locality.lower() not in venue.lower() else venue
    if not venue_full or not any(k in venue_full.lower() for k in _BALI_RES):
        print(f"[{SOURCE}] skipping vague/non-Bali venue: {title!r}", file=sys.stderr)
        return None

    # Discovery window: today -> +14d only.
    today = datetime.now().date()
    horizon = today + timedelta(days=_WINDOW_DAYS)
    if not (today <= start_dt.date() <= horizon):
        return None

    description = _text(block.get("description", ""))
    offers = block.get("offers") if isinstance(block.get("offers"), dict) else {}
    price = str(offers.get("price", "")) if offers else ""
    is_free = price == "0"
    rsvp = _text(offers.get("url", "")) if offers else ""
    if rsvp:
        description = (description + f" (RSVP: {rsvp})").strip()
    organizer = block.get("organizer") if isinstance(block.get("organizer"), dict) else {}
    org = _text(organizer.get("name", "")) if organizer else ""
    if org:
        description = (description + f" (Organizer: {org})").strip()
    description = description[:4000]

    # Prefer the per-event Luma RSVP URL as source_url (distinct per
    # event); fall back to the listing (block "url" points there too).
    source_url = rsvp or _text(block.get("url", "")) or LISTING_URL

    return {
        "name": title,
        "title": title,
        "start": start,
        "finish": finish,
        "location": venue_full,
        "description": description,
        "area": venue_full,
        "category": "tech",
        "cost": "Free" if is_free else None,
        "free": True if is_free else None,
        "source_url": source_url,
        "status": "confirmed",
    }


def fetch() -> list[dict]:
    """Fetch raw Canggu tech events from remotebuilders.io.

    Returns a list of dicts (possibly empty). Raises RuntimeError when
    the listing yields zero dated JSON-LD Event blocks (parser assert:
    a redesign pages us instead of silently emptying the feed).
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        listing_html = _get(session, LISTING_URL)
        if not listing_html:
            return []
        blocks = _collect_blocks(listing_html)
        if not blocks:
            raise RuntimeError(
                f"parser assert failed: no JSON-LD Event blocks on {LISTING_URL}"
            )

        events: list[dict] = []
        for block in blocks:
            try:
                event = _parse_block(block)
            except Exception as exc:
                print(f"[{SOURCE}] parse failed for {block.get('name')}: {exc}",
                      file=sys.stderr)
                continue
            if event is None:
                continue
            events.append(event)
        print(f"[{SOURCE}] {len(events)} in-window events from {len(blocks)} JSON-LD blocks")
        time.sleep(1 + random.random())
        if not events:
            # Blocks parsed fine but every event fell outside today ->
            # +14d. Quiet fortnight: return [] so the orchestrator keeps
            # last-good state instead of erroring.
            print(f"[{SOURCE}] 0 in-window events from {len(blocks)} "
                  f"blocks (outside today -> +14d); returning []")
            return []
        return events
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"[{SOURCE}] fetch failed: {exc}", file=sys.stderr)
        return []
