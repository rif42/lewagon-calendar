"""JSON-state merge for the Bali events pipeline.

Data flow: sources/*.py -> normalize -> merge (state.json) -> emit
(data/events.json + data/bali-events.ics from ONE merged list).

State shape (JSON-serialisable)::

    {
        "events": {uid: canonical_event_dict, ...},
        "missed": {uid: int, ...},   # consecutive runs absent from input
        "sources": {name: {...}, ...}  # owned by the orchestrator, untouched here
    }

For backwards tolerance, ``state["events"]`` is also accepted as a list of
event dicts (converted to uid-keyed dict internally) and a missing/empty
state is treated as first run.

Canonical event fields (per contract)::

    uid, name, location, description, start_utc, finish_utc, area, category,
    cost, free, source_url, source, discovered_at, last_seen_at, sequence,
    status (confirmed|needs_review|stale|cancelled)
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

# Fields excluded when deciding whether an event "changed".
_IGNORED_DIFF_FIELDS = frozenset({"last_seen_at", "sequence"})


def _events_to_dict(events) -> dict:
    """Normalise stored state events (dict or list) to a uid-keyed dict."""
    if not events:
        return {}
    if isinstance(events, dict):
        return dict(events)
    by_uid = {}
    for ev in events:
        if isinstance(ev, dict) and ev.get("uid"):
            by_uid[ev["uid"]] = ev
    return by_uid


def _is_changed(old: dict, new: dict) -> bool:
    """True if any canonical field (excl. last_seen_at/sequence) differs."""
    keys = set(old.keys()) | set(new.keys())
    keys -= _IGNORED_DIFF_FIELDS
    for key in keys:
        if key in ("discovered_at",):
            # discovered_at is merge-owned; incoming value never counts.
            continue
        if old.get(key) != new.get(key):
            return True
    return False


def merge(new_events: list[dict], state: dict, run_id: str) -> tuple[list, dict]:
    """Merge normalised incoming events into stored state.

    Args:
        new_events: normalised canonical event dicts for this run.
        state: previous state dict (``events``/``missed``/``sources``).
        run_id: opaque run identifier (e.g. ISO timestamp). Written to
            ``discovered_at``/``last_seen_at`` for new/seen events.

    Returns:
        (merged, new_state): merged is the full event list to emit;
        new_state is the state to persist as state.json.

    Rules:
        - new uid -> append (discovered_at=last_seen_at=run_id, sequence 0).
        - changed (field diff excl. last_seen_at/sequence) -> update +
          sequence+1, last_seen_at=run_id.
        - seen unchanged -> last_seen_at=run_id, sequence kept.
        - missing 1 run -> keep unchanged (last_seen_at untouched).
        - missing 2 consecutive runs -> status "stale" (sequence+1), kept.
        - missing 3 consecutive runs -> dropped from merged + state.
        - empty input list -> last-good: return stored events unchanged,
          state untouched (never wipe on a single bad run).
        - state["sources"] is passed through untouched.
    """
    state = copy.deepcopy(state) if state else {}
    prev_by_uid = _events_to_dict(state.get("events"))
    missed: dict = dict(state.get("missed") or {})

    # Empty-input guard: never wipe state on a single bad/empty run.
    if not new_events:
        merged = [copy.deepcopy(ev) for ev in prev_by_uid.values()]
        new_state = dict(state)
        new_state.setdefault("events", dict(prev_by_uid))
        new_state.setdefault("missed", dict(missed))
        new_state.setdefault("sources", dict(state.get("sources") or {}))
        return merged, new_state

    incoming_by_uid: dict = {}
    for ev in new_events:
        if isinstance(ev, dict) and ev.get("uid"):
            # Last duplicate wins; duplicates within one run are a
            # normaliser concern, not a merge concern.
            incoming_by_uid[ev["uid"]] = ev

    merged_by_uid: dict = {}
    new_missed: dict = {}

    # Seen / new / changed.
    for uid, incoming in incoming_by_uid.items():
        old = prev_by_uid.get(uid)
        if old is None:
            ev = copy.deepcopy(incoming)
            ev["discovered_at"] = run_id
            ev["last_seen_at"] = run_id
            ev["sequence"] = 0
            merged_by_uid[uid] = ev
            new_missed[uid] = 0
        elif _is_changed(old, incoming):
            ev = copy.deepcopy(incoming)
            ev["discovered_at"] = old.get("discovered_at", run_id)
            ev["last_seen_at"] = run_id
            try:
                seq = int(old.get("sequence", 0))
            except (TypeError, ValueError):
                seq = 0
            ev["sequence"] = seq + 1
            merged_by_uid[uid] = ev
            new_missed[uid] = 0
        else:
            ev = copy.deepcopy(old)
            ev["last_seen_at"] = run_id
            merged_by_uid[uid] = ev
            new_missed[uid] = 0

    # Missing: keep / stale / drop.
    for uid, old in prev_by_uid.items():
        if uid in incoming_by_uid:
            continue
        count = int(missed.get(uid, 0) or 0) + 1
        if count >= 3:
            # Dropped: absent from merged and from new state entirely.
            continue
        ev = copy.deepcopy(old)
        if count >= 2:
            if ev.get("status") != "stale":
                ev["status"] = "stale"
                try:
                    seq = int(ev.get("sequence", 0))
                except (TypeError, ValueError):
                    seq = 0
                ev["sequence"] = seq + 1
            new_missed[uid] = count
        else:
            new_missed[uid] = count
        merged_by_uid[uid] = ev

    merged = list(merged_by_uid.values())
    new_state = dict(state)
    new_state["events"] = copy.deepcopy(merged_by_uid)
    new_state["missed"] = dict(new_missed)
    new_state.setdefault("sources", dict(state.get("sources") or {}))
    return merged, new_state


def _parse_dt(value):
    """Parse an ISO-8601 str (incl. trailing Z) or date/datetime to aware dt."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # Plain YYYY-MM-DD without time component.
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _day_start(value):
    """Lower window bound: start of the given day (UTC) or exact datetime."""
    dt = _parse_dt(value)
    if dt is None:
        return None
    if isinstance(value, str) and len(value.strip()) == 10:
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if isinstance(value, datetime) and value.tzinfo is None:
        return dt  # naive datetime used as exact bound
    return dt.replace(hour=0, minute=0, second=0, microsecond=0) if (
        isinstance(value, str) and "T" not in value.strip()
    ) else dt


def _day_end(value):
    """Upper window bound: end of the given day (UTC) or exact datetime."""
    dt = _parse_dt(value)
    if dt is None:
        return None
    if isinstance(value, datetime):
        return dt
    text = value.strip()
    if "T" in text:
        return dt
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)


def prune_window(events: list[dict], yesterday, plus60d) -> list[dict]:
    """Keep events overlapping the rolling window [yesterday, +60d].

    An event is kept when its interval overlaps the window, i.e.
    ``finish >= start(yesterday)`` and ``start <= end(plus60d)``.
    Bounds accept ISO strings (date or datetime), dates, or datetimes.
    Events with unparseable/missing dates are kept (never silently drop).
    """
    start = _day_start(yesterday)
    end = _day_end(plus60d)
    if start is None or end is None:
        return list(events)
    kept = []
    for ev in events:
        ev_start = _parse_dt(ev.get("start_utc")) if isinstance(ev, dict) else None
        ev_end = _parse_dt(ev.get("finish_utc")) if isinstance(ev, dict) else None
        if ev_start is None and ev_end is None:
            kept.append(ev)
            continue
        effective_start = ev_start or ev_end
        effective_end = ev_end or ev_start
        if effective_end >= start and effective_start <= end:
            kept.append(ev)
    return kept
