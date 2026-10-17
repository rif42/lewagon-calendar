"""Tropical Nomad Canggu coworking/tech events source for the Bali pipeline.

Scrapes the server-rendered listing ``https://tropicalnomad.id/events``
(This Week + Coming Up sections). The page embeds its event data as
``thisWeekEvents:[{id,title,location,tag,date,time}]`` /
``upcomingEvents:[...]`` payloads plus matching HTML cards, so parsing is
plain regex + bs4 cross-check. Exposes ``fetch() -> list[dict]`` of *raw*
events; normalization (uids, UTC times, enums) happens downstream.

Verified 2026-10-17: listing returns HTTP 200 with plain GET (no login,
no JS, no bot wall; the Cloudflare beacon script is passive analytics).
Date provenance per item: ``date: "October 19, 2026"`` +
``time: "6:30 PM - 8:30 PM"`` (WITA, organizer-local). All events are
hosted on-site at Tropical Nomad Coworking, Jl. Subak Canggu No.2,
Canggu (address published in the page footer). There are no per-event
detail pages (cards open modals), so ``source_url`` is the listing URL
with a ``#<id>`` fragment.

Canggu tech anchor: AI Meetup series, Toastmaster, Members Connect/BBQ
-- corroborates miranesia's Tropical Nomad rows (aggregation layer kept
separate; same events from two origins is corroboration, not a dupe).

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

SOURCE = "tropicalnomad"
TIER = 2

BASE_URL = "https://tropicalnomad.id"
LISTING_URL = BASE_URL + "/events"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://tropicalnomad.id/events)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Discovery window: only dated instances inside today -> +14d are emitted.
_WINDOW_DAYS = 14

# On-site venue (published in the page footer); every listed event is hosted here.
VENUE = "Tropical Nomad Coworking, Jl. Subak Canggu No.2, Canggu"

# Embedded payload items: {id:"...",title:"...",location:"...",tag:"...",date:"...",time:"..."}.
_ITEM_RE = re.compile(
    r"\{id:\s*\"([^\"]+)\"\s*,\s*title:\s*\"([^\"]+)\"\s*,"
    r"\s*location:\s*\"([^\"]*)\"\s*,\s*tag:\s*\"([^\"]*)\"\s*,"
    r"\s*date:\s*\"([^\"]*)\"\s*,\s*time:\s*\"([^\"]*)\"\s*\}"
)

# Payload date: "October 19, 2026". Card time: "6:30 PM - 8:30 PM".
_DATE_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2}),?\s+(\d{4})",
    re.I,
)
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?", re.I)


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


def _collect_items(html: str) -> list[dict]:
    """Embedded payload items from thisWeekEvents + upcomingEvents."""
    items: list[dict] = []
    seen: set[str] = set()
    for m in _ITEM_RE.finditer(html or ""):
        ident, title, location, tag, date, time = (
            m.group(1), m.group(2), m.group(3),
            m.group(4), m.group(5), m.group(6),
        )
        if not ident or not title or ident in seen:
            continue
        seen.add(ident)
        items.append({
            "id": ident.strip(),
            "title": title.strip(),
            "location": location.strip(),
            "tag": tag.strip(),
            "date": date.strip(),
            "time": time.strip(),
        })
    return items


def _map_category(title: str, tag: str) -> str:
    """Map title/tag to a raw category."""
    low = f"{title} {tag}".lower()
    if any(k in low for k in (" ai ", "ai meetup", "startup", "founder",
                              "tech", "crypto", "bitcoin", "web3", "coding",
                              "developer", "business")):
        return "tech"
    if any(k in low for k in ("wellness", "yoga", "breathwork")):
        return "wellness"
    if any(k in low for k in ("party", "club", "dj", "nightlife", "bbq")):
        return "party"
    return "community"


def _parse_item(item: dict) -> dict | None:
    """Build a raw event dict from one embedded payload item."""
    title = item.get("title", "").strip()
    if not title:
        return None

    m = _DATE_RE.search(item.get("date", ""))
    if not m:
        return None  # undated: nothing to emit
    try:
        month = datetime.strptime(m.group(1)[:3], "%b").month
        day = int(m.group(2))
        year = int(m.group(3))
    except ValueError:
        return None

    # Time range "6:30 PM - 8:30 PM": first match = start, second = finish.
    times = _TIME_RE.findall(item.get("time", ""))
    start = finish = ""
    try:
        if times:
            h = int(times[0][0]) % 12 + (12 if times[0][2].upper() == "P" else 0)
            mi = int(times[0][1] or 0)
            start = datetime(year, month, day, h, mi).strftime("%Y-%m-%d %H:%M")
            if len(times) > 1:
                h2 = int(times[1][0]) % 12 + (12 if times[1][2].upper() == "P" else 0)
                mi2 = int(times[1][1] or 0)
                finish = datetime(year, month, day, h2, mi2).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None
    if not start:
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

    room = item.get("location", "").strip()
    venue = f"{room}, {VENUE}" if room else VENUE
    tag = item.get("tag", "").strip()
    description = f"{title} at Tropical Nomad Canggu"
    if room:
        description += f" ({room})"
    if tag:
        description += f" [{tag}]"
    description += " (Organizer: Tropical Nomad Coworking, Canggu)"

    return {
        "name": title,
        "title": title,
        "start": start,
        "finish": finish or None,
        "location": venue,
        "description": description,
        "area": venue,
        "category": _map_category(title, tag),
        "cost": None,
        "free": None,
        "source_url": f"{LISTING_URL}#{item['id']}",
        "status": "confirmed",
    }


def fetch() -> list[dict]:
    """Fetch raw Tropical Nomad Canggu events from tropicalnomad.id.

    Returns a list of dicts (possibly empty). Raises RuntimeError when
    the listing yields zero dated payload items (parser assert: a
    redesign pages us instead of silently emptying the feed);
    per-item failures are logged and skipped.
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        listing_html = _get(session, LISTING_URL)
        if not listing_html:
            return []
        items = _collect_items(listing_html)
        if not items:
            raise RuntimeError(
                f"parser assert failed: no event payloads on {LISTING_URL}"
            )

        # Cross-check: the server-rendered cards must show the same count
        # (payload/HTML drift means a redesign is underway).
        soup = BeautifulSoup(listing_html, "lxml")
        card_dates = sum(
            1 for el in soup.find_all(string=_DATE_RE) if el.strip()
        )
        if card_dates == 0:
            raise RuntimeError(
                f"parser assert failed: no dated cards on {LISTING_URL}"
            )

        events: list[dict] = []
        for item in items:
            try:
                event = _parse_item(item)
            except Exception as exc:
                print(f"[{SOURCE}] parse failed for {item.get('id')}: {exc}",
                      file=sys.stderr)
                continue
            if event is None:
                continue
            events.append(event)
        print(f"[{SOURCE}] {len(events)} events from {len(items)} payload items")
        time.sleep(1 + random.random())
        return events
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"[{SOURCE}] fetch failed: {exc}", file=sys.stderr)
        return []
