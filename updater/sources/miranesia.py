"""Miranesia Bali tech-events source for the Bali events pipeline.

Scrapes the server-rendered hub ``https://miranesia.com/bali/tech``
(``ul.hub-evlist > li > a.hub-ev-link``: absolute detail hrefs whose slugs
embed ``YYYY-MM-DD`` + hex id, ``.hub-ev-title`` + ``.hub-ev-meta``
"Thu 15 Oct, 09:00 - Venue, Area" + ``.hub-ev-tags``) plus one detail page
per event (schema.org JSON-LD ``Event``: name/url/startDate/endDate with
+08:00 offset/description/location/organizer; breadcrumb corroborates
area/category). Exposes ``fetch() -> list[dict]`` of *raw* events;
normalization (uids, UTC times, enums) happens downstream.

Verified 2026-10-15: hub returns HTTP 200 with plain GET (no login, no JS,
no bot wall); 41 dated tech links island-wide. Aggregation layer: detail
``offers.url``/upstream links (lu.ma, eventbrite) may overlap eventbrite.py
rows -- merge dedupes on content, and booking URLs are kept in the
description for corroboration, same Discotech/Beat pattern.

Only Bali-venue events inside the discovery window (today -> +14d) are
emitted. Non-Bali rows never occur on this hub; vague/off-island venues
are rejected per hoax-check rules.

requests + beautifulsoup only. No browser, no login, no JS.
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

SOURCE = "miranesia"
TIER = 2

BASE_URL = "https://miranesia.com"
LISTING_URL = BASE_URL + "/bali/tech"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://miranesia.com/bali/tech)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Discovery window: only dated instances inside today -> +14d are emitted.
_WINDOW_DAYS = 14

# Detail slugs embed the event date: /bali/<area>/<slug>-YYYY-MM-DD-<hexid>/.
_EVENT_HREF_RE = re.compile(r"^/bali/[^/]+/.+-(\d{4})-(\d{2})-(\d{2})-[0-9a-f]{6,}/?$")

# Listing meta: "Thu 15 Oct, 09:00 - Venue, Area" (time optional).
_META_RE = re.compile(
    r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+(\d{1,2})\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*"
    r"(?:,?\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?)?",
    re.I,
)

# Bali-scope guard (hub is Bali-only; belt-and-braces for hoax-check).
_BALI_RES = (
    "bali", "canggu", "ubud", "denpasar", "kuta", "badung", "gianyar",
    "pererenan", "berawa", "tumbak bayuh", "uluwatu", "seminyak",
    "kerobokan", "tabanan", "seseh", "munggu", "echo beach", "batu bolong",
    "sanur", "sayan", "petitenget", "kayu manis", "tropical nomad",
    "bitcoin house", "bwork",
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


def _collect_links(html: str) -> list[dict]:
    """Listing cards: detail url + slug date + title/meta/tags text."""
    soup = BeautifulSoup(html, "lxml")
    cards: list[dict] = []
    seen: set[str] = set()
    for anchor in soup.select("a.hub-ev-link"):
        href = (anchor.get("href") or "").split("?")[0]
        if not href.startswith("http"):
            href = BASE_URL + href if href.startswith("/") else href
        if not href.startswith(BASE_URL + "/bali/"):
            continue
        path = href[len(BASE_URL):]
        m = _EVENT_HREF_RE.match(path)
        if not m:
            continue
        url = href.rstrip("/") + "/"
        if url in seen:
            continue
        seen.add(url)
        cards.append({
            "url": url,
            "slug_ymd": (int(m.group(1)), int(m.group(2)), int(m.group(3))),
            "title": _text(anchor.select_one(".hub-ev-title")),
            "meta": _text(anchor.select_one(".hub-ev-meta")),
            "tags": _text(anchor.select_one(".hub-ev-tags")),
        })
    return cards


def _parse_json_ld(soup: BeautifulSoup) -> dict:
    """First schema.org Event JSON-LD block as a dict ({} on miss)."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "Event":
                return item
    return {}


def _parse_detail(html: str, url: str, card: dict) -> dict | None:
    """Build a raw event dict from a detail page + listing card."""
    soup = BeautifulSoup(html, "lxml")
    ld = _parse_json_ld(soup)

    title = str(ld.get("name") or "").strip() or card.get("title", "")
    if not title:
        return None

    # Start: JSON-LD startDate (WITA +08:00 offset) corroborated by the
    # slug-embedded date; mismatch means skip.
    start_raw = str(ld.get("startDate") or "").strip()
    try:
        start_dt = datetime.fromisoformat(start_raw)
    except ValueError:
        return None
    if start_dt.tzinfo is None:
        return None  # no offset: refuse to guess the zone
    ymd = card.get("slug_ymd")
    wita_day = start_dt.astimezone(
        start_dt.tzinfo
    ).date()  # same wall-clock day the slug names
    if ymd is not None and (wita_day.year, wita_day.month, wita_day.day) != tuple(ymd):
        print(f"[{SOURCE}] date mismatch slug vs detail: {url}",
              file=sys.stderr)
        return None
    start = start_dt.strftime("%Y-%m-%d %H:%M")

    finish = None
    try:
        end_dt = datetime.fromisoformat(str(ld.get("endDate") or ""))
        if end_dt.tzinfo is not None and end_dt > start_dt:
            finish = end_dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        finish = None

    # Venue: JSON-LD location name + locality; must read Bali (hoax-check:
    # never invent a venue string, never emit off-island rows).
    loc = ld.get("location") if isinstance(ld.get("location"), dict) else {}
    venue = str((loc or {}).get("name") or "").strip()
    addr = (loc or {}).get("address") if isinstance((loc or {}).get("address"), dict) else {}
    locality = str((addr or {}).get("addressLocality") or "").strip()
    if locality and locality.lower() not in venue.lower():
        venue = f"{venue}, {locality}" if venue else locality
    if not venue:
        # Fallback: listing meta tail ("... - Venue, Area").
        meta = card.get("meta", "")
        if "·" in meta:
            venue = meta.split("·", 1)[1].strip()
        elif "-" in meta:
            venue = meta.rsplit("-", 1)[1].strip()
    if not venue or not any(k in venue.lower() for k in _BALI_RES):
        print(f"[{SOURCE}] skipping vague/non-Bali venue: {url}",
              file=sys.stderr)
        return None

    # Discovery window: today -> +14d only.
    try:
        start_day = datetime.strptime(start, "%Y-%m-%d %H:%M").date()
    except ValueError:
        return None
    today = datetime.now().date()
    horizon = today + timedelta(days=_WINDOW_DAYS)
    if not (today <= start_day <= horizon):
        return None

    description = str(ld.get("description") or "").strip()
    offers = ld.get("offers") if isinstance(ld.get("offers"), dict) else {}
    booking = str((offers or {}).get("url") or "").strip()
    organizer = ""
    org = ld.get("organizer")
    if isinstance(org, dict) and org.get("name"):
        organizer = str(org["name"]).strip()
    elif isinstance(org, str):
        organizer = org.strip()
    if organizer and organizer.lower() not in description.lower():
        description = (description + f" (Organizer: {organizer})").strip()
    if booking and booking.lower() not in description.lower():
        description = (description + f" Register: {booking}").strip()
    description = description[:4000]

    offers_price = str((offers or {}).get("price") or "").strip()
    cost = offers_price or None

    return {
        "name": title,
        "title": title,
        "start": start,
        "finish": finish,
        "location": venue,
        "description": description,
        "area": venue,
        "category": "tech",
        "cost": cost,
        "free": ("free" in (cost or "").lower() or "free" in description.lower()) or None,
        "source_url": url,
        "status": "confirmed",
    }


def fetch() -> list[dict]:
    """Fetch raw Bali tech events from miranesia.com.

    Returns a list of dicts (possibly empty). Raises RuntimeError when
    the hub yields zero dated links (parser assert: a redesign pages us
    instead of silently emptying the feed); per-page failures are logged
    and skipped.
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        listing_html = _get(session, LISTING_URL)
        if not listing_html:
            return []
        cards = _collect_links(listing_html)
        if not cards:
            raise RuntimeError(
                f"parser assert failed: no dated links on {LISTING_URL}"
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
        print(f"[{SOURCE}] {len(events)} events from {len(cards)} links")
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
