"""Baligasm events source for the Bali events pipeline.

Scrapes the public listing at https://baligasm.com/events plus one detail
page per event (``/event/<slug>``). Exposes ``fetch() -> list[dict]`` of
*raw* events; normalization (uids, UTC times, enums) happens downstream.

requests + beautifulsoup only. No browser, no login, no JS.
"""

from __future__ import annotations

import random
import re
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

SOURCE = "baligasm"
TIER = 1

BASE_URL = "https://baligasm.com"
LISTING_URL = BASE_URL + "/events"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewallon-event-calendar/1.0 (+https://baligasm.com)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
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


def _parse_cards(html: str) -> list[dict]:
    """Extract per-event summary data from the /events listing cards."""
    soup = BeautifulSoup(html, "lxml")
    cards: list[dict] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=re.compile(r"^/event/")):
        href = anchor.get("href", "")
        if not href or href in seen:
            continue
        seen.add(href)
        url = BASE_URL + href

        title = ""
        h3 = anchor.find("h3")
        if h3:
            title = _text(h3)
        if not title:
            img = anchor.find("img")
            if img:
                title = (img.get("alt") or "").strip()

        # Area badge: small pill, top-left of the card image.
        area = ""
        badge = anchor.select_one("span.absolute.top-4.left-4")
        if badge:
            area = _text(badge)
        if not area:
            for pill in anchor.select("span.rounded-full"):
                txt = _text(pill)
                if txt and txt.lower() != "featured" and len(txt) <= 20:
                    area = txt
                    break

        # Venue: truncated span with the location icon.
        venue = ""
        vspan = anchor.select_one("span.truncate")
        if vspan:
            venue = _text(vspan)

        # Date badge: MON + day number block on the card image.
        month, day = "", ""
        datebox = anchor.select_one("div.w-12")
        if datebox:
            parts = [p for p in datebox.find_all("span")]
            if len(parts) >= 2:
                month, day = _text(parts[0]), _text(parts[1])

        # Time row: e.g. "Fri · 12:00 PM".
        time_text = ""
        for span in anchor.find_all("span"):
            txt = _text(span)
            if "·" in txt and re.search(r"\d", txt):
                time_text = txt
                break

        cards.append(
            {
                "source_url": url,
                "title": title,
                "area": area,
                "venue": venue,
                "month": month,
                "day": day,
                "time_text": time_text,
            }
        )
    return cards


def _iso_when(text: str) -> str:
    """'Saturday, September 26, 2026, 6:00 AM' -> '2026-09-26 06:00' ('' on miss)."""
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),\s+(\d{4})", text, re.I)
    if not m:
        return ""
    try:
        day = datetime.strptime(
            "%s %s, %s" % (m.group(1), m.group(2), m.group(3)), "%B %d, %Y")
    except ValueError:
        return ""
    t = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([AP]M)", text, re.I)
    hour, minute = ((int(t.group(1)) % 12 + (12 if t.group(3).upper() == "PM" else 0),
                     int(t.group(2) or 0)) if t else (0, 0))
    return day.replace(hour=hour, minute=minute).strftime("%Y-%m-%d %H:%M")

def _guess_category(label: str) -> str:
    """Map a detail-page category label to a raw category string."""
    low = (label or "").lower()
    if "party" in low:
        return "party"
    if "music" in low:
        return "music"
    if "food" in low or "din" in low or "culinar" in low:
        return "food"
    if "art" in low:
        return "art"
    if "cultur" in low:
        return "culture"
    if "wellness" in low or "yoga" in low or "retreat" in low:
        return "wellness"
    if "sport" in low or "surf" in low or "run" in low:
        return "sport"
    if "market" in low:
        return "market"
    if "tech" in low:
        return "tech"
    if "communit" in low:
        return "community"
    return "other"


def _parse_detail(html: str, card: dict) -> dict:
    """Build a raw event dict from an event detail page."""
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    title = _text(h1) or card.get("title", "")

    # Badges above the title live in the flex div preceding the h1:
    # [status-ish, area, category]. (Scoped to that div so the header
    # meta row below the h1 -- venue, date, time spans -- is not picked up.)
    area = card.get("area", "")
    category_label = ""
    status = "confirmed"
    if h1 is not None:
        badges = h1.find_previous_sibling("div")
        pills = [_text(s) for s in badges.find_all("span")] if badges else []
        pills = [p for p in pills if p]
        if pills:
            if "cancel" in pills[0].lower():
                status = "cancelled"
            rest = [p for p in pills if p.lower() not in ("upcoming", "featured")]
            if rest:
                area = rest[0] or area
            if len(rest) >= 2:
                category_label = rest[-1]

    # "When" info card: date line + time line.
    date_line, time_line = "", ""
    when = soup.find(string=re.compile(r"^\s*When\s*$"))
    if when is not None and getattr(when, "parent", None) is not None:
        box = when.parent.parent
        if box is not None:
            lines = [_text(p) for p in box.find_all("p")]
            lines = [ln for ln in lines if ln and ln.lower() != "when"]
            if lines:
                date_line = lines[0]
            if len(lines) > 1:
                time_line = lines[1]
    if date_line:
        start = date_line + (", " + time_line if time_line else "")
    elif card.get("month") or card.get("day"):
        start = " ".join(
            p
            for p in (
                card.get("month", ""),
                card.get("day", ""),
                card.get("time_text", ""),
            )
            if p
        )
    else:
        start = card.get("time_text", "")
    start = re.sub(r"\s+,", ",", start)
    # Normalize to ISO for the pipeline; keep raw on miss.
    iso = _iso_when(start)
    if iso:
        start = iso

    # "Where" info card: venue + street address.
    venue, address = card.get("venue", ""), ""
    where = soup.find(string=re.compile(r"^\s*Where\s*$"))
    if where is not None and getattr(where, "parent", None) is not None:
        box = where.parent.parent
        if box is not None:
            lines = [_text(p) for p in box.find_all("p")]
            lines = [ln for ln in lines if ln and ln.lower() != "where"]
            if lines:
                venue = lines[0]
            if len(lines) > 1:
                address = lines[1]
    location = venue + (", " + address if address else "")

    # "About the Event" section body.
    description = ""
    about = soup.find(string=re.compile(r"About the Event"))
    if about is not None and getattr(about, "parent", None) is not None:
        body = about.parent.find_next_sibling("div")
        if body is not None:
            description = _text(body)[:4000]

    # Ticket link, folded into the description for downstream use.
    tickets = soup.find("a", string=re.compile(r"Get Tickets"))
    if tickets is not None and tickets.get("href"):
        link = tickets.get("href").strip()
        if link:
            suffix = "Tickets: " + link
            description = (description + " " + suffix).strip()[:4000]

    return {
        "name": title,
        "title": title,
        "start": start,
        "finish": None,
        "location": location,
        "description": description,
        "area": area,
        "category": _guess_category(category_label),
        "cost": None,
        "free": None,
        "source_url": card.get("source_url", ""),
        "status": status,
    }


def fetch() -> list[dict]:
    """Fetch raw events from baligasm.com.

    Returns a list of dicts (possibly empty). Never raises: any failure
    is logged to stderr and results in ``[]`` (or a card-fallback list
    when detail pages fail but the listing parsed).
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        listing_html = _get(session, LISTING_URL)
        if not listing_html:
            return []
        cards = _parse_cards(listing_html)
        if not cards:
            print(f"[{SOURCE}] no event cards found on {LISTING_URL}", file=sys.stderr)
            return []

        events: list[dict] = []
        for index, card in enumerate(cards):
            if index:
                time.sleep(1 + random.random())  # 1-2s between page fetches
            detail_html = _get(session, card["source_url"])
            if detail_html:
                try:
                    events.append(_parse_detail(detail_html, card))
                except Exception as exc:
                    print(
                        f"[{SOURCE}] parse failed for {card['source_url']}: {exc}",
                        file=sys.stderr,
                    )
                    events.append(_card_fallback(card))
            else:
                events.append(_card_fallback(card))
        return events
    except Exception as exc:
        print(f"[{SOURCE}] fetch failed: {exc}", file=sys.stderr)
        return []


def _card_fallback(card: dict) -> dict:
    """Minimal raw event from listing-card data when the detail page fails."""
    title = card.get("title", "")
    start = " ".join(
        p
        for p in (card.get("month", ""), card.get("day", ""), card.get("time_text", ""))
        if p
    )
    return {
        "name": title,
        "title": title,
        "start": start,
        "finish": None,
        "location": card.get("venue", ""),
        "description": "",
        "area": card.get("area", ""),
        "category": "other",
        "cost": None,
        "free": None,
        "source_url": card.get("source_url", ""),
        "status": "confirmed",
    }
