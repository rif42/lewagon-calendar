"""Emit JSON + ICS + last_run payloads from ONE merged event list.

Guarantee 1: ``events_json_str``, ``ics_str`` and ``last_run_dict`` are all
derived from the same ``events`` input, so the site (JSON) and the Subscribe
feed (ICS) can never disagree.

Canonical event fields (see README section 8)::

    uid, name, location, description, start_utc, finish_utc, area, category,
    cost, free, source_url, source, discovered_at, last_seen_at, sequence,
    status

Dates are UTC ``Z`` strings (``YYYY-MM-DDTHH:MM:SSZ``); date-only strings
(``YYYY-MM-DD``) or a truthy ``all_day`` flag mark all-day events.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    _WITA = ZoneInfo("Asia/Makassar")
except Exception:  # pragma: no cover - zoneinfo data missing
    _WITA = None

ICS_WARN_BYTES = 500 * 1024
UID_SUFFIX = "@lewagon-calendar"

DISCLAIMER = "Please verify with the organizer before attending."

_STATUS_MAP = {
    "confirmed": "CONFIRMED",
    "cancelled": "CANCELLED",
    "needs_review": "TENTATIVE",
    "stale": "TENTATIVE",
}

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _escape_text(value: object) -> str:
    """Escape a TEXT property value per RFC 5545 section 3.3.11."""
    text = "" if value is None else str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "\\n")


def _fold_line(line: str, limit: int = 75) -> list[str]:
    """Fold a content line to <= ``limit`` octets per RFC 5545 section 3.1."""
    raw = line.encode("utf-8")
    if len(raw) <= limit:
        return [line]
    parts: list[str] = []
    chunk = b""
    current_len = 0
    first = True
    for char in line:
        encoded = char.encode("utf-8")
        budget = limit if first else limit - 1  # continuation adds a space
        if current_len + len(encoded) > budget and chunk:
            parts.append(chunk.decode("utf-8"))
            chunk = b""
            current_len = 0
            first = False
            budget = limit - 1
        chunk += encoded
        current_len += len(encoded)
    if chunk:
        parts.append(chunk.decode("utf-8"))
    # RFC 5545 §3.1: each continuation line MUST start with a single space.
    return [parts[0]] + [" " + p for p in parts[1:]]


def _parse_dt(value: object) -> datetime | None:
    """Parse a UTC ``Z`` / ISO / date-only string into an aware datetime."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    if _DATE_ONLY_RE.match(text):
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _is_all_day(event: dict) -> bool:
    if event.get("all_day") is True:
        return True
    start = str(event.get("start_utc") or "").strip()
    if _DATE_ONLY_RE.match(start):
        return True
    # Legacy rows emitted before the all_day flag: date-only input normalizes
    # to midnight WITA (16:00:00Z the previous day), so that signature with a
    # matching-or-absent finish means "no time of day was ever scraped".
    if start.endswith("T16:00:00Z"):
        finish = str(event.get("finish_utc") or "").strip()
        return not finish or finish.endswith("T16:00:00Z")
    return False


def _all_day_date(value: object, fallback: datetime) -> str:
    """Return ``YYYYMMDD`` for an all-day boundary.

    Timed midnight-WITA values are converted back to the WITA calendar day
    so Bali viewers see the correct date.
    """
    text = str(value or "").strip()
    if _DATE_ONLY_RE.match(text):
        return text.replace("-", "")
    parsed = _parse_dt(value) or fallback
    if _WITA is not None:
        parsed = parsed.astimezone(_WITA)
    return parsed.strftime("%Y%m%d")


def _describe(event: dict) -> str:
    """Build DESCRIPTION: body + source URL + organizer disclaimer."""
    chunks: list[str] = []
    body = str(event.get("description") or "").strip()
    if body:
        chunks.append(body)
    source_url = str(event.get("source_url") or "").strip()
    if source_url:
        chunks.append("More info: " + source_url)
    chunks.append(DISCLAIMER)
    return _escape_text("\n\n".join(chunks))


def _event_lines(event: dict, dtstamp: str) -> list[str]:
    uid = str(event.get("uid") or "").strip()
    start = _parse_dt(event.get("start_utc"))
    if not uid or start is None:
        return []
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}{UID_SUFFIX}",
        f"DTSTAMP:{dtstamp}",
        f"SEQUENCE:{int(event.get('sequence', 0) or 0)}",
        f"SUMMARY:{_escape_text(event.get('name') or 'Untitled event')}",
    ]
    location = str(event.get("location") or "").strip()
    if location:
        lines.append(f"LOCATION:{_escape_text(location)}")
    lines.append(f"DESCRIPTION:{_describe(event)}")
    source_url = str(event.get("source_url") or "").strip()
    if source_url:
        lines.append(f"URL:{source_url}")
    status = _STATUS_MAP.get(str(event.get("status") or "").strip().lower())
    lines.append(f"STATUS:{status or 'CONFIRMED'}")
    if _is_all_day(event):
        finish = _parse_dt(event.get("finish_utc"))
        end_day = _all_day_date(
            event.get("finish_utc"), start + timedelta(days=1)
        )
        lines.append(f"DTSTART;VALUE=DATE:{_all_day_date(event.get('start_utc'), start)}")
        # DATE DTEND is exclusive; a missing/degenerate finish means +1 day.
        if finish is not None and finish <= start:
            end_day = _all_day_date(None, start + timedelta(days=1))
        lines.append(f"DTEND;VALUE=DATE:{end_day}")
    else:
        finish = _parse_dt(event.get("finish_utc"))
        if finish is None or finish <= start:
            finish = start + timedelta(hours=1)
        lines.append(f"DTSTART:{_format_stamp(start)}")
        lines.append(f"DTEND:{_format_stamp(finish)}")
    lines.append("END:VEVENT")
    folded: list[str] = []
    for line in lines:
        folded.extend(_fold_line(line))
    return folded


def emit(
    events: list[dict],
    prog_name: str = "lewagon-event-calendar",
    sources: dict | None = None,
    ran_at: datetime | None = None,
) -> tuple[str, str, dict]:
    """Build ``(events_json_str, ics_str, last_run_dict)`` from one list.

    ``sources`` (per-source orchestrator status) passes straight through
    into ``last_run_dict``; ``ran_at`` overrides "now" (UTC) for DTSTAMP
    and ``last_run_dict["ran_at"]``.
    """
    ordered = sorted(events, key=lambda event: str(event.get("start_utc") or ""))
    events_json_str = json.dumps(ordered, indent=2, ensure_ascii=False) + "\n"

    now = ran_at if ran_at is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    dtstamp = _format_stamp(now)
    ran_at_iso = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    body: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{prog_name}//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{prog_name}",
    ]
    for event in ordered:
        body.extend(_event_lines(event, dtstamp))
    body.append("END:VCALENDAR")
    ics_str = "\r\n".join(body) + "\r\n"

    if len(ics_str.encode("utf-8")) > ICS_WARN_BYTES:
        print(
            f"warning: ICS feed is {len(ics_str.encode('utf-8'))} bytes, "
            "over the 500KB budget"
        )

    last_run_dict = {
        "ran_at": ran_at_iso,
        "event_count": len(ordered),
        "sources": dict(sources) if sources is not None else {},
    }
    return events_json_str, ics_str, last_run_dict
