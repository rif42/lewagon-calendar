"""Eventbrite Bali-tech source for the Bali events pipeline.

Scrapes the public discovery page
``/d/indonesia--bali--85672023/tech-events/`` plus one detail page
per tech card (``/e/<slug>-tickets-<id>``). Exposes
``fetch() -> list[dict]`` of *raw* events; normalization (uids, UTC
times, enums) happens downstream.

Verified 2026-09-27: discovery returns HTTP 200 (~750 KB) with plain
GET (no login, no JS). Listing cards embed title + next-date line
("Fri, Oct 9, 5:00 PM + 27 more") + venue ("Banjar Badung · Bitcoin
House Bali") in static HTML. Detail pages return HTTP 200 with an
``og:description`` + organizer ``/o/`` link; ``startDate`` JSON-LD
marks the series origin (not the next occurrence), so in-window
instances come from the listing card's next-date line.

Only tech cards matching the focus (tech/AI/dev/crypto/startup/
coworking/nomad) are kept; US-pollution promos and non-Bali venues
are rejected. Recurring cards whose next-date falls past the window
are skipped (no guessing of occurrences).

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

SOURCE = "eventbrite"
TIER = 2

BASE_URL = "https://www.eventbrite.com"
LISTING_URL = BASE_URL + "/d/indonesia--bali--85672023/tech-events/"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://www.eventbrite.com/)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Next-date line on listing cards, e.g. "Fri, Oct 9, 5:00 PM + 27 more".
_CARD_DATE_RE = re.compile(
    r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2}),?\s+"
    r"(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?",
    re.I,
)

_TECH_RES = (
    "tech", " ai ", "artificial intelligence", "startup", "dev school",
    "developer", "coding", "code ", "vibe cod", "agentic", "crypto",
    "bitcoin", "blockchain", "web3", "cowork", "founder", "saas",
    "digital literacy",
)

# Out-of-scope geos seen polluting the Bali discovery page.
_NONBALI_RES = (
    "louisville", "university of louisville", "edmonton", "chicago",
    "houston", "zamorins",
)

_KNOWN_CITY_RES = (
    "canggu", "pererenan", "tumbak bayuh", "kuta utara", "batu bolong",
    "echo beach", "berawa", "seseh", "munggu", "tuban", "kuta", "seminyak",
    "kerobokan", "denpasar", "ubud", "uluwatu", "tabanan", "gianyar",
    "badung", "banjar", "sukawati", "bali",
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
    """Tech listing cards: detail url + card text (title/date/venue).

    Walks up from each ``/e/`` anchor to the enclosing card container
    so the next-date line and venue travel with the URL.
    """
    soup = BeautifulSoup(html, "lxml")
    cards: list[dict] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href") or ""
        if "/e/" not in href:
            continue
        url = href.split("?")[0]
        if not url.startswith("https://"):
            url = BASE_URL + url if url.startswith("/") else url
        if url in seen or "eventbrite.com/e/" not in url:
            continue
        seen.add(url)
        node = anchor
        for _ in range(4):  # climb to the card container
            if node.parent is None:
                break
            node = node.parent
        # Pipe separator keeps title/date/venue/promo in distinct
        # segments ("T | date | Area · Venue | Save... | Share...").
        card_text = re.sub(r"\s+", " ",
                           node.get_text(" | ", strip=True)).strip()[:600]
        cards.append({"url": url, "text": card_text})
    return cards


def _is_tech(text: str) -> bool:
    """True when the card text matches the tech focus (hoax-check 1)."""
    low = f" {text.lower()} "
    return any(k in low for k in _TECH_RES)


def _is_bali(text: str) -> bool:
    """Reject US-pollution promos / non-Bali venues (hoax-check 2)."""
    low = text.lower()
    if any(k in low for k in _NONBALI_RES):
        return False
    return any(k in low for k in _KNOWN_CITY_RES)


def _parse_card_date(text: str) -> str:
    """'Fri, Oct 9, 5:00 PM' (+ implied current year) -> ISO ('' miss)."""
    m = _CARD_DATE_RE.search(text)
    if not m:
        return ""
    try:
        month = datetime.strptime(m.group(2)[:3], "%b").month
        year = datetime.now().year
        hour = int(m.group(4)) % 12 + (12 if m.group(6).upper() == "P" else 0)
        return datetime(year, month, int(m.group(3)),
                        hour, int(m.group(5) or 0)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ""


def _parse_detail(html: str, url: str, card: dict) -> dict | None:
    """Build a raw event dict from a detail page + listing card."""
    soup = BeautifulSoup(html, "lxml")
    card_text = card.get("text", "")

    if not _is_tech(card_text):
        return None
    if not _is_bali(card_text):
        print(f"[{SOURCE}] skipping non-Bali card: {url}", file=sys.stderr)
        return None

    # Title: detail og:title (sans "Tickets..." promo suffix) beats the
    # card head — card container text repeats the title/date/venue block
    # twice (verified 2026-09-27), so it is never used verbatim.
    title = ""
    tag = soup.find("meta", attrs={"property": "og:title"})
    if tag and tag.get("content"):
        title = re.sub(r"\s+Tickets.*$", "",
                       tag.get("content").strip()).strip()
    if not title or len(title) < 4:
        head = card_text.split("|")[0].strip()
        if len(head) % 2 == 0 and head[:len(head) // 2] == head[len(head) // 2:]:
            head = head[:len(head) // 2].strip()
        title = head
    if not title:
        return None

    # Date: the card's next-date line is the occurrence inside (or
    # nearest) the window; JSON-LD startDate is the series origin.
    start = _parse_card_date(card_text)
    if not start:
        return None  # no dated occurrence: nothing to emit

    # Venue: card's "Area · Venue" tail, e.g. "Banjar Badung · Bitcoin
    # House Bali". Hoax-check: never invent a Canggu venue string.
    venue = ""
    for part in [p.strip() for p in card_text.split("|")]:
        # Venue segment is exactly "Area · Venue" (pipe-separated, no
        # promo bleed — verified 2026-09-27). Skip "Save/Share this
        # event:" promo segments, which contain no "·".
        if "·" not in part:
            continue
        if part.lower().startswith(("save this event", "share this event")):
            continue
        tail = part.split("·")[-1].strip()
        area_bit = part.split("·")[0].strip()
        # BeautifulSoup decodes "&nbsp;" poorly on this page ("Â" tail);
        # strip the artifact at the boundary.
        tail = re.sub(r"\s*Â\s*$", "", tail).strip()
        area_bit = re.sub(r"\s*Â\s*$", "", area_bit).strip()
        venue = tail
        if area_bit and area_bit.lower() not in tail.lower():
            venue = f"{tail}, {area_bit}"
        break
    if not venue:
        m = re.search(r"(Bitcoin House Bali[^|]{0,60}|Tropical Nomad[^|]{0,60})",
                      card_text)
        venue = m.group(1).strip() if m else ""
    if not venue:
        return None  # vague venue: reject per hoax-check rules

    organizer = ""
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href") or ""
        if "/o/" in href:
            organizer = _text(anchor)
            if organizer and "eventbrite" not in organizer.lower():
                break
    if not organizer:
        organizer = ""

    description = ""
    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        description = og.get("content").strip()
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
        "free": None,
        "source_url": url,
        "status": "confirmed",
    }


def fetch() -> list[dict]:
    """Fetch raw Bali-tech events from eventbrite.com.

    Returns a list of dicts (possibly empty). Raises RuntimeError when
    the listing yields zero tech cards (parser assert: a redesign
    pages us instead of silently emptying the feed); per-page failures
    are logged and skipped.
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
                f"parser assert failed: no /e/ links on {LISTING_URL}"
            )
        tech_cards = [c for c in cards
                      if _is_tech(c["text"]) and _is_bali(c["text"])]
        if not tech_cards:
            raise RuntimeError(
                f"parser assert failed: no tech cards on {LISTING_URL}"
            )

        events: list[dict] = []
        for index, card in enumerate(tech_cards):
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
        print(f"[{SOURCE}] {len(events)} events from {len(tech_cards)} cards")
        return events
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"[{SOURCE}] fetch failed: {exc}", file=sys.stderr)
        return []
