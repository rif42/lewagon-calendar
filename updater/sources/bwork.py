"""BWork Canggu coworking/tech events source for the Bali events pipeline.

Scrapes the server-rendered listing ``https://bwork.id/canggu/`` (cards:
``div.single-event`` with ``.bigdate`` MON DD + linked ``h3`` title +
Time/Place + excerpt) plus one detail page per event. Exposes
``fetch() -> list[dict]`` of *raw* events; normalization (uids, UTC
times, enums) happens downstream.

Verified 2026-10-02: listing returns HTTP 200 with plain GET (no login,
no JS, no bot wall). Date provenance per card: ``.bigdate`` month/day +
``Time : HPM`` + detail-page ``Date : D, MON YYYY`` cross-check.
Detail pages carry ``Date : D, MON YYYY`` / ``Time`` / ``Place`` in
``ul.detailevent``; the Time field is unreliable (renders "& PM"),
so time-of-day comes from the listing card's ``Time :`` line and the
detail page is used for description + organizer + date corroboration.

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

SOURCE = "bwork"
TIER = 2

BASE_URL = "https://bwork.id"
LISTING_URL = BASE_URL + "/canggu/"
TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://bwork.id/canggu/)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Discovery window: only dated instances inside today -> +14d are emitted.
_WINDOW_DAYS = 14

# Detail slugs live under /canggu/<slug>/ (feed/xml/json/oembed/page links excluded).
_EVENT_HREF_RE = re.compile(r"^/canggu/[^/]+/?$")

# Card "Time : 6.30PM" / "Time : 5PM" line.
_CARD_TIME_RE = re.compile(r"Time\s*:\s*(\d{1,2})(?:[.:](\d{2}))?\s*([AP])\.?M\.?", re.I)

# Detail "Date : 7, OCT 2026" line.
_DETAIL_DATE_RE = re.compile(
    r"Date\s*:\s*(\d{1,2}),?\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})",
    re.I,
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
    """Listing cards: detail url + bigdate month/day + card text."""
    soup = BeautifulSoup(html, "lxml")
    cards: list[dict] = []
    seen: set[str] = set()
    for block in soup.select("div.single-event"):
        anchor = block.find("a", href=True)
        if anchor is None:
            continue
        href = (anchor.get("href") or "").split("?")[0]
        if not href.startswith("http"):
            href = BASE_URL + href if href.startswith("/") else href
        path = "/" + href.split("bwork.id/")[-1].rstrip("/")
        if not _EVENT_HREF_RE.match(path + "/"):
            continue
        url = BASE_URL + path + "/"
        if url in seen:
            continue
        seen.add(url)
        bigdate = block.select_one(".bigdate")
        month = day = ""
        if bigdate is not None:
            parts = [_text(d) for d in bigdate.find_all("div")]
            if len(parts) >= 2:
                month, day = parts[0], parts[1]
        cards.append({
            "url": url,
            "month": month,
            "day": day,
            "text": _text(block)[:1200],
        })
    return cards


def _map_category(title: str, description: str) -> str:
    """Map title/description to a raw category."""
    low = f"{title} {description}".lower()
    if any(k in low for k in ("startup", "founder", "tech", " ai ", "crypto",
                              "bitcoin", "web3", "coding", "developer",
                              "marketing", "meta ads", "business", "mastermind")):
        return "tech"
    if any(k in low for k in ("wellness", "yoga", "breathwork")):
        return "wellness"
    if any(k in low for k in ("party", "club", "dj", "nightlife")):
        return "party"
    return "community"


def _parse_detail(html: str, url: str, card: dict) -> dict | None:
    """Build a raw event dict from a detail page + listing card."""
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    title = _text(h1)
    if not title:
        return None

    body = soup.get_text(" ", strip=True)

    # Date: detail "Date : D, MON YYYY" corroborated by the card bigdate.
    start = ""
    m = _DETAIL_DATE_RE.search(body)
    if m:
        try:
            month = datetime.strptime(m.group(2)[:3], "%b").month
            day = int(m.group(1))
            year = int(m.group(3))
        except ValueError:
            return None
        # Cross-check: card bigdate must name the same month/day.
        try:
            card_month = datetime.strptime(card["month"][:3], "%b").month
            card_day = int(re.search(r"\d+", card["day"]).group())
            if (card_month, card_day) != (month, day):
                print(f"[{SOURCE}] date mismatch card vs detail: {url}",
                      file=sys.stderr)
                return None
        except (ValueError, AttributeError, TypeError):
            pass  # card bigdate unreadable: trust the detail page
        # Time-of-day from the listing card (detail Time field is "& PM").
        hour, minute = 18, 0  # evening default, never invent precision
        tm = _CARD_TIME_RE.search(card["text"])
        timed = bool(tm)
        if tm:
            try:
                hour = int(tm.group(1)) % 12 + (12 if tm.group(3).upper() == "P" else 0)
                minute = int(tm.group(2) or 0)
            except ValueError:
                timed = False
        try:
            start = datetime(year, month, day, hour, minute).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return None
    if not start:
        return None  # undated: nothing to emit

    # Venue: detail "Place : ..." line; must name BWork (hoax-check:
    # never invent a Canggu venue string).
    venue = ""
    pm = re.search(r"Place\s*:\s*([^|]{3,80}?)(?:\s{2,}|\s*[A-Z][a-z]+-to-|\s*Join|\s*Register|$)", body)
    if pm:
        venue = _text(pm.group(1))
    if "bwork" not in venue.lower():
        return None  # vague/off-site venue: reject per hoax-check rules

    # Discovery window: today -> +14d only.
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    today = datetime.now().date()
    horizon = today + timedelta(days=_WINDOW_DAYS)
    if not (today <= start_dt.date() <= horizon):
        return None

    organizer = ""
    om = re.search(r"Hosted by\s+([^|.(]{3,80})", body)
    if om:
        organizer = _text(om.group(1))

    description = ""
    paras = sorted((_text(p) for p in soup.find_all("p")),
                   key=len, reverse=True)
    description = next((p for p in paras if len(p) > 40), "")
    if organizer and organizer.lower() not in description.lower():
        description = (description + f" (Organizer: {organizer})").strip()
    join = soup.find("a", string=re.compile(r"Join This Event", re.I))
    if join and join.get("href"):
        reg = join.get("href").strip()
        if reg and reg.lower() not in description.lower():
            description = (description + f" Register: {reg}").strip()
    description = description[:4000]

    return {
        "name": title,
        "title": title,
        "start": start,
        "finish": None,
        "location": venue,
        "description": description,
        "area": venue,
        "category": _map_category(title, description),
        "cost": None,
        "free": None,
        "source_url": url,
        "status": "confirmed",
    }


def fetch() -> list[dict]:
    """Fetch raw Canggu coworking/tech events from bwork.id.

    Returns a list of dicts (possibly empty). Raises RuntimeError when
    the listing yields zero dated cards (parser assert: a redesign
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
