"""Luma (lu.ma) calendars source for the Bali events pipeline.

Polls the public lu.ma calendar API for Canggu-tech calendars, currently the
BWork Bali coworking calendar (``https://luma.com/bworkbali``). Exposes
``fetch() -> list[dict]`` of *raw* events; normalization (uids, UTC times,
enums) happens downstream.

Verified 2026-10-24: ``GET https://api.lu.ma/calendar/get-items
?calendar_api_id=<id>`` returns HTTP 200 JSON with plain GET (no login, no
bot wall, no JS). The calendar api_id is discoverable server-side from the
public calendar page's ``__NEXT_DATA__`` payload
(``props.pageProps.initialData.data.calendar.api_id``, e.g.
``cal-TyC1Ai9wRnwJt0p``). Payload ``entries[]`` carry per-event ``start_at /
end_at`` ISO UTC, ``name``, ``url`` slug (-> ``https://luma.com/<slug>``),
``timezone``, and ``geo_address_info`` (``full_address`` names BWork Bali,
Canggu; coordinates included). Same upstream as the ``bwork`` source
(bwork.id cards link the same events) -- one corroboration cluster, dedupe
via merge.

Only Canggu-venue events are kept (address/geo must name Canggu/Pererenan/
Berawa/Batu Bolong/Tumbak Bayuh or BWork); other lu.ma calendars' rows are
out of scope.

requests only. No browser, no login, no JS.
"""

from __future__ import annotations

import random
import re
import sys
import time
from datetime import datetime, timedelta

import requests

SOURCE = "luma"
TIER = 2

TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 "
        "lewagon-event-calendar/1.0 (+https://luma.com/bworkbali)"
    ),
    "Accept": "application/json, text/html",
    "Accept-Language": "en-US,en;q=0.9",
}

# Discovery window: only dated instances inside today -> +14d are emitted.
_WINDOW_DAYS = 14

# Public lu.ma calendars polled: (label, page URL, calendar api_id).
# api_id is read from the page's __NEXT_DATA__ (props.pageProps.
# initialData.data.calendar.api_id); re-verify if the API 404s.
CALENDARS = [
    ("BWork Bali", "https://luma.com/bworkbali", "cal-TyC1Ai9wRnwJt0p"),
]

API_URL = "https://api.lu.ma/calendar/get-items?calendar_api_id={api_id}"

# Canggu-scope venue filter: keep Canggu-area rows only (hoax-check: never
# invent a Canggu venue string, never emit Denpasar/Java rows as Canggu).
_CANGGU_RES = (
    "canggu", "bwork", "pererenan", "berawa", "batu bolong", "batubolong",
    "tumbak bayuh", "seseh", "munggu", "echo beach", "kayu manis", "nelayan",
)


def _text(value) -> str:
    """Single-line cleaned text (None-safe)."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _get(session: requests.Session, url: str) -> dict | list | None:
    """GET url as JSON, returning the parsed payload or None on failure."""
    try:
        resp = session.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # per-calendar failure must not kill the run
        print(f"[{SOURCE}] GET failed for {url}: {exc}", file=sys.stderr)
        return None


def _parse_entry(entry: dict, calendar_label: str,
                 calendar_url: str) -> dict | None:
    """Build a raw event dict from one get-items entry."""
    ev = entry.get("event") if isinstance(entry, dict) else None
    if not isinstance(ev, dict):
        return None
    name = _text(ev.get("name"))
    start_at = _text(ev.get("start_at"))
    if not name or not start_at:
        return None  # undated: nothing to emit

    # Time: start_at/end_at are ISO UTC already ("...Z"); normalize layer
    # also accepts ISO, so pass WITA wall-time "YYYY-MM-DD HH:MM" computed
    # from the UTC instant (WITA = UTC+8, no DST).
    try:
        start_dt = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
        start_wita = start_dt + timedelta(hours=8)
        start = start_wita.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None
    finish = None
    end_at = _text(ev.get("end_at"))
    if end_at:
        try:
            end_dt = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
            finish = (end_dt + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            finish = None

    # Venue: geo full_address (e.g. "BWork Bali Coworking Space & Cafe,
    # Jl. Nelayan No.9C, Canggu, ..."); must name the Canggu area.
    geo = ev.get("geo_address_info") or {}
    venue = _text(geo.get("full_address") or geo.get("short_address")
                  or ev.get("location") or ev.get("address"))
    if not venue or not any(k in venue.lower() for k in _CANGGU_RES):
        return None  # off-site/out-of-scope row: reject per hoax-check rules

    # Discovery window: today -> +14d only.
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d %H:%M").date()
    except ValueError:
        return None
    today = datetime.now().date()
    horizon = today + timedelta(days=_WINDOW_DAYS)
    if not (today <= start_date <= horizon):
        return None

    slug = _text(ev.get("url"))
    source_url = f"https://luma.com/{slug}" if slug else calendar_url
    description = f"{calendar_label} via lu.ma"
    cal = entry.get("calendar") if isinstance(entry, dict) else None
    if isinstance(cal, dict) and _text(cal.get("description_short")):
        description = _text(cal.get("description_short"))
    if slug and slug not in description:
        description = (description + f" Register: https://luma.com/{slug}").strip()
    description = description[:4000]

    low = f"{name} {description}".lower()
    if any(k in low for k in ("startup", "founder", "tech", " ai ", "crypto",
                              "bitcoin", "web3", "coding", "developer",
                              "marketing", "mastermind", "grok", "bot")):
        category = "tech"
    elif any(k in low for k in ("yoga", "wellness", "breathwork", "bahasa")):
        category = "wellness" if "yoga" in low or "wellness" in low or "breathwork" in low else "community"
    else:
        category = "community"

    return {
        "name": name,
        "title": name,
        "start": start,
        "finish": finish,
        "location": venue,
        "description": description,
        "area": venue,
        "category": category,
        "cost": None,
        "free": None,
        "source_url": source_url,
        "status": "confirmed",
    }


def fetch() -> list[dict]:
    """Fetch raw Canggu-tech events from polled lu.ma calendars.

    Returns a list of dicts (possibly empty). Raises RuntimeError when no
    polled calendar yields an entry list (parser assert: an API redesign
    pages us instead of silently emptying the feed); per-entry failures
    are logged and skipped.
    """
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        got_entries = False
        events: list[dict] = []
        for label, page_url, api_id in CALENDARS:
            payload = _get(session, API_URL.format(api_id=api_id))
            entries = payload.get("entries") if isinstance(payload, dict) else None
            if not isinstance(entries, list):
                print(f"[{SOURCE}] no entry list for {label} ({page_url})",
                      file=sys.stderr)
                continue
            got_entries = True
            for entry in entries:
                try:
                    event = _parse_entry(entry, label, page_url)
                except Exception as exc:
                    print(f"[{SOURCE}] parse failed for entry: {exc}",
                          file=sys.stderr)
                    continue
                if event is None:
                    continue
                events.append(event)
            time.sleep(1 + random.random())  # 1-2s between calendars
        if not got_entries:
            raise RuntimeError(
                "parser assert failed: no lu.ma calendar yielded an entry list"
            )
        print(f"[{SOURCE}] {len(events)} events from {len(CALENDARS)} calendar(s)")
        return events
    except RuntimeError:
        raise
    except Exception as exc:
        print(f"[{SOURCE}] fetch failed: {exc}", file=sys.stderr)
        return []
