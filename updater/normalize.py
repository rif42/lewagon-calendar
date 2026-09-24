"""Raw-event normalisation for the Bali events pipeline.

Data flow: sources/*.py -> normalize -> merge (state.json) -> emit
(data/events.json + data/bali-events.ics from ONE merged list).

Pure functions only; no network, no disk, stdlib only. Invalid rows
return ``None`` so callers can skip them.

Raw input shape (per source)::

    {name|title, start, finish, location, description,
     area, category, cost, free, source_url, status}

Aliases tolerated: ``title`` for ``name``, ``start_utc``/``date``/
``datetime`` for ``start``, ``finish_utc``/``end`` for ``finish``,
``url``/``link`` for ``source_url``.

Canonical output matches events.schema.json (WITA parsed to UTC Z,
uid = sha1(source|norm_title|start_utc)).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    _WITA = ZoneInfo("Asia/Makassar")
except Exception:  # pragma: no cover - zoneinfo data missing
    _WITA = None

# Fixed UTC+8 fallback when zoneinfo data is unavailable (WITA has no DST).
_WITA_OFFSET = timezone(timedelta(hours=8))

__all__ = ["to_utc_iso", "norm_title", "make_uid", "normalize"]

AREA_ENUM = ("Canggu", "Seminyak", "Uluwatu", "Ubud", "Denpasar", "Tabanan", "Other")
CATEGORY_ENUM = (
    "Music",
    "Surf",
    "Wellness",
    "Food & Drink",
    "Coworking & Tech",
    "Arts & Culture",
    "Nightlife",
    "Other",
)
STATUS_ENUM = ("confirmed", "needs_review", "stale", "cancelled")

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _wita_tz():
    return _WITA if _WITA is not None else _WITA_OFFSET


def to_utc_iso(value: object) -> str | None:
    """Parse a WITA/UTC ISO-8601 (or date-only) value to a UTC ``Z`` string.

    Rules:
      - aware datetimes / offsets / trailing ``Z`` -> converted to UTC.
      - naive datetimes / ISO strings without offset -> assumed WITA (UTC+8).
      - date-only ``YYYY-MM-DD`` -> midnight WITA -> ``16:00:00Z`` previous day.
      - ``date`` objects -> same as date-only.
    Returns ``YYYY-MM-DDTHH:MM:SSZ`` (seconds precision) or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_wita_tz())
        return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=_wita_tz())
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    if _DATE_ONLY_RE.match(text):
        try:
            dt = datetime(int(text[0:4]), int(text[5:7]), int(text[8:10]), tzinfo=_wita_tz())
        except ValueError:
            return None
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        # fromisoformat handles "YYYY-MM-DD HH:MM[:SS]" (space separator) too.
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_wita_tz())
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_title(title: object) -> str:
    """Normalise a title for uid stability: NFKC, collapse space, casefold."""
    text = unicodedata.normalize("NFKC", str(title or ""))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def make_uid(source: object, title: object, start_utc: object) -> str:
    """Stable id: lowercase hex sha1(source|norm_title|start_utc)."""
    payload = f"{str(source or '').strip()}|{norm_title(title)}|{str(start_utc or '').strip()}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _norm_enum(value: object, mapping: list[tuple[str, str]], valid: tuple[str, ...]) -> str:
    """Map free text to the nearest enum member, else ``"Other"``."""
    if value is None:
        return "Other"
    text = str(value).strip()
    if not text:
        return "Other"
    lowered = text.casefold()
    for canonical in valid:
        if lowered == canonical.casefold():
            return canonical
    for keyword, canonical in mapping:
        if keyword in lowered:
            return canonical
    return "Other"


_AREA_KEYWORDS: list[tuple[str, str]] = [
    ("canggu", "Canggu"),
    ("seminyak", "Seminyak"),
    ("uluwatu", "Uluwatu"),
    ("ubud", "Ubud"),
    ("denpasar", "Denpasar"),
    ("tabanan", "Tabanan"),
]

_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    ("coworking", "Coworking & Tech"),
    ("tech", "Coworking & Tech"),
    ("startup", "Coworking & Tech"),
    ("coding", "Coworking & Tech"),
    ("developer", "Coworking & Tech"),
    ("food", "Food & Drink"),
    ("drink", "Food & Drink"),
    ("culinary", "Food & Drink"),
    ("dinner", "Food & Drink"),
    ("brunch", "Food & Drink"),
    ("restaurant", "Food & Drink"),
    ("coffee", "Food & Drink"),
    ("nightlife", "Nightlife"),
    ("party", "Nightlife"),
    ("parties", "Nightlife"),
    ("club", "Nightlife"),
    ("rave", "Nightlife"),
    ("music", "Music"),
    ("concert", "Music"),
    ("gig", "Music"),
    ("band", "Music"),
    ("dj", "Music"),
    ("wellness", "Wellness"),
    ("yoga", "Wellness"),
    ("meditation", "Wellness"),
    ("retreat", "Wellness"),
    ("spa", "Wellness"),
    ("healing", "Wellness"),
    ("breathwork", "Wellness"),
    ("surf", "Surf"),
    ("sport", "Surf"),
    ("art", "Arts & Culture"),
    ("cultur", "Arts & Culture"),
    ("exhibition", "Arts & Culture"),
    ("gallery", "Arts & Culture"),
    ("theatr", "Arts & Culture"),
    ("theater", "Arts & Culture"),
    ("dance", "Arts & Culture"),
    ("film", "Arts & Culture"),
    ("craft", "Arts & Culture"),
    ("market", "Arts & Culture"),
    ("community", "Arts & Culture"),
]


def _norm_status(value: object) -> str:
    if isinstance(value, str) and value.strip().casefold() in STATUS_ENUM:
        return value.strip().casefold()
    return "confirmed"


def _norm_free(raw: dict) -> bool:
    free = raw.get("free")
    if isinstance(free, bool):
        return free
    cost = raw.get("cost")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        return cost == 0
    if isinstance(cost, str) and "free" in cost.casefold():
        return True
    if isinstance(cost, str) and cost.strip() == "0":
        return True
    return False


def _norm_cost(value: object):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    return text if text else None


def normalize(raw: object, source: str, run_id: str) -> dict | None:
    """Map one raw event dict to a canonical event dict, or ``None``.

    Drops (returns ``None``) when ``name``/``start``/``source_url``
    is missing or when ``start`` is unparseable. ``finish`` problems
    degrade to ``None`` instead of dropping the row.
    """
    if not isinstance(raw, dict):
        return None
    src = str(source or raw.get("source") or "").strip()
    if not src:
        return None

    name = raw.get("name", raw.get("title", ""))
    name = str(name or "").strip()
    if not name:
        return None

    start_raw = raw.get("start", raw.get("start_utc", raw.get("date", raw.get("datetime"))))
    start_utc = to_utc_iso(start_raw)
    if not start_utc:
        return None

    source_url = raw.get("source_url", raw.get("url", raw.get("link", "")))
    source_url = str(source_url or "").strip()
    if not source_url:
        return None

    finish_raw = raw.get("finish", raw.get("finish_utc", raw.get("end")))
    finish_utc = to_utc_iso(finish_raw) if finish_raw not in (None, "") else None

    location = str(raw.get("location") or "").strip()
    description = str(raw.get("description") or "").strip()

    return {
        "uid": make_uid(src, name, start_utc),
        "name": name,
        "location": location,
        "description": description,
        "start_utc": start_utc,
        "finish_utc": finish_utc,
        "area": _norm_enum(raw.get("area", raw.get("location")), _AREA_KEYWORDS, AREA_ENUM),
        "category": _norm_enum(raw.get("category"), _CATEGORY_KEYWORDS, CATEGORY_ENUM),
        "cost": _norm_cost(raw.get("cost")),
        "free": _norm_free(raw),
        "source_url": source_url,
        "source": src,
        "discovered_at": run_id,
        "last_seen_at": run_id,
        "sequence": 0,
        "status": _norm_status(raw.get("status")),
    }
