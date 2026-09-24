"""Nightly orchestrator for the Bali events pipeline.

Flow: discover ``updater/sources/*.py`` -> ``fetch()`` each (isolated) ->
normalize each raw dict via ``normalize.py`` -> ``merge()`` against
``data/state.json`` -> ``prune_window()`` to the rolling 60-day window ->
``emit()`` -> write ``data/events.json``, ``data/bali-events.ics``,
``data/state.json``, ``data/last_run.json``.

A source module is any ``*.py`` file in ``updater/sources/`` (excluding
``_``-prefixed and ``__init__``) exposing a ``fetch() -> list[dict]``
callable. Optional module attributes honoured here:

- ``SOURCE_NAME`` (str): display/key name; defaults to the file stem.
- ``TIER`` (int/str): tier label used by ``--tier`` filtering.

Any per-source failure (import error, missing ``fetch``, exception
inside ``fetch``, bad return value) is recorded in the per-source
status map and yields ``[]`` so the rest of the run continues.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCES_DIR = HERE / "sources"
DEFAULT_DATA_DIR = ROOT / "data"

# Import sibling pipeline modules, working whether this file runs as
# ``python updater/update.py`` (script mode) or ``python -m updater.update``.
try:  # package mode: python -m updater.update
    from updater.merge import merge, prune_window
except ImportError:  # script mode: python updater/update.py
    sys.path.insert(0, str(HERE))
    try:
        from merge import merge, prune_window
    except ImportError:  # pragma: no cover - updater/ not importable
        merge = None  # type: ignore[assignment]
        prune_window = None  # type: ignore[assignment]

try:
    from updater.emit_ics import emit
except ImportError:
    try:
        from emit_ics import emit
    except ImportError:  # pragma: no cover
        emit = None  # type: ignore[assignment]

try:
    from updater.normalize import normalize as normalize_event
except ImportError:
    try:
        from normalize import normalize as normalize_event
    except ImportError:
        normalize_event = None  # type: ignore[assignment]


def discover_sources(sources_dir: Path | None = None) -> list[tuple[str, Path]]:
    """Return ``[(stem, path), ...]`` sorted by stem for source modules."""
    directory = Path(sources_dir) if sources_dir else SOURCES_DIR
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_") or path.name == "__init__.py":
            continue
        found.append((path.stem, path))
    return found


def load_module(stem: str, path: Path):
    """Import a source file by path; raises on failure (caller isolates)."""
    spec = importlib.util.spec_from_file_location(f"lewagon_sources.{stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"lewagon_sources.{stem}"] = module
    spec.loader.exec_module(module)
    return module


def safe_fetch(stem: str, path: Path) -> tuple[str, list, dict, object]:
    """Import + ``fetch()`` one source, never raising.

    Returns ``(name, raws, status, module)`` where ``status`` is
    ``{"status": "ok"|"error", "count": <raw count>, ...}`` and a
    failing source yields ``raws == []`` with ``status["error"]`` set.
    """
    name = stem
    try:
        module = load_module(stem, path)
    except Exception as exc:  # noqa: BLE001 - isolation is the point
        return name, [], {
            "status": "error",
            "count": 0,
            "error": f"import failed: {exc}",
        }, None
    name = str(getattr(module, "SOURCE_NAME", stem) or stem)
    fetch = getattr(module, "fetch", None)
    if not callable(fetch):
        return name, [], {
            "status": "error",
            "count": 0,
            "error": "no fetch() callable",
        }, module
    try:
        raws = fetch()
    except Exception as exc:  # noqa: BLE001 - one bad source must not kill the run
        traceback.print_exc()
        return name, [], {
            "status": "error",
            "count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }, module
    if not isinstance(raws, list):
        return name, [], {
            "status": "error",
            "count": 0,
            "error": f"fetch() returned {type(raws).__name__}, expected list",
        }, module
    return name, raws, {"status": "ok", "count": len(raws)}, module


def normalize_all(raws: list, source_name: str, run_id: str = "") -> tuple[list[dict], int]:
    """Normalize raw dicts; per-event failures are skipped and counted."""
    normalized: list[dict] = []
    errors = 0
    # normalize.normalize(raw, source, run_id) in the current contract;
    # tolerate 2-arg variants by adapting to the declared signature.
    three_arg = False
    if normalize_event is not None:
        try:
            import inspect as _inspect
            _params = list(_inspect.signature(normalize_event).parameters.values())
            _required = [
                p for p in _params
                if p.default is _inspect.Parameter.empty
                and p.kind in (_inspect.Parameter.POSITIONAL_ONLY,
                              _inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            three_arg = len(_required) >= 3
        except (TypeError, ValueError):
            three_arg = False
    for raw in raws:
        try:
            if normalize_event is not None:
                event = (normalize_event(raw, source_name, run_id)
                         if three_arg else normalize_event(raw, source_name))
            elif isinstance(raw, dict):
                event = raw
            else:
                raise TypeError(f"raw event is {type(raw).__name__}, expected dict")
            if isinstance(event, dict) and event.get("uid"):
                normalized.append(event)
            else:
                errors += 1
        except Exception:  # noqa: BLE001 - skip one bad event, keep the run
            errors += 1
    return normalized, errors

def load_state(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {"events": {}, "missed": {}, "sources": {}}
    if not isinstance(state, dict):
        return {"events": {}, "missed": {}, "sources": {}}
    state.setdefault("events", {})
    state.setdefault("missed", {})
    state.setdefault("sources", {})
    return state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run all Bali event sources and rebuild data/ outputs.",
    )
    parser.add_argument(
        "--tier",
        default=None,
        help="Only run sources whose TIER attribute equals this value.",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Only run the source module with this file stem (or SOURCE_NAME).",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Directory for events.json, bali-events.ics, state.json, last_run.json.",
    )
    parser.add_argument(
        "--sources-dir",
        default=str(SOURCES_DIR),
        help="Directory to discover source modules in.",
    )
    parser.add_argument(
        "--no-sleep",
        action="store_true",
        help="Skip the politeness sleep between sources.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict:
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    discovered = discover_sources(Path(args.sources_dir))
    if args.source:
        discovered = [
            (stem, path)
            for stem, path in discovered
            if stem == args.source or stem == (args.source or "").strip()
        ]
        # Also match against SOURCE_NAME lazily: keep stems matching is the
        # common case; names are resolved after import below.
    if args.tier is not None:
        wanted = str(args.tier)
        kept = []
        for stem, path in discovered:
            try:
                module = load_module(stem, path)
            except Exception:  # noqa: BLE001 - import errors surface in safe_fetch
                kept.append((stem, path))
                continue
            tier = getattr(module, "TIER", None)
            if tier is None or str(tier) == wanted:
                kept.append((stem, path))
            # Remove the pre-import so safe_fetch re-imports a fresh module.
            sys.modules.pop(f"lewagon_sources.{stem}", None)
        discovered = kept

    now = datetime.now(timezone.utc)
    run_id = now.isoformat().replace("+00:00", "Z")

    all_normalized: list[dict] = []
    statuses: dict[str, dict] = {}
    for index, (stem, path) in enumerate(discovered):
        if index > 0 and not args.no_sleep:
            time.sleep(random.uniform(1, 2))
        name, raws, status, _module = safe_fetch(stem, path)
        if args.source and args.source not in (stem, name):
            continue
        normalized, norm_errors = normalize_all(raws, name, run_id)
        status["normalized"] = len(normalized)
        if norm_errors:
            status["normalize_errors"] = norm_errors
        if status.get("status") == "ok" and norm_errors and not normalized:
            status["status"] = "error"
            status["error"] = f"{norm_errors} event(s) failed normalization"
        all_normalized.extend(normalized)
        statuses[name] = status
        print(
            f"{name}: raw={status.get('count', 0)} "
            f"normalized={len(normalized)} status={status.get('status')}"
            + (f" error={status['error']}" if status.get("error") else "")
        )
    if not discovered:
        print("no sources discovered; emitting from stored state.")

    state = load_state(data_dir / "state.json")
    # Preserve previous per-source entries for sources not run this time.
    merged_sources = dict(state.get("sources") or {})
    merged_sources.update(statuses)

    if merge is None or prune_window is None:
        raise RuntimeError("merge.py is unavailable; cannot build state.")
    merged, new_state = merge(all_normalized, state, run_id)
    windowed = prune_window(merged, now - timedelta(days=1), now + timedelta(days=60))
    new_state["sources"] = merged_sources

    if emit is None:
        raise RuntimeError("emit_ics.py is unavailable; cannot emit outputs.")
    events_json_str, ics_str, last_run = emit(
        windowed, sources=merged_sources, ran_at=now
    )

    (data_dir / "events.json").write_text(events_json_str, encoding="utf-8")
    # ICS MUST keep single CRLF per line (RFC 5545; Google rejects LF-only
    # and broken feeds). write_text() in text mode translates "\n" into the
    # OS line separator on Windows, turning emit()'s "\r\n" into "\r\r\n",
    # so the feed is written with newline="" to pass endings through intact.
    with open(data_dir / "bali-events.ics", "w", encoding="utf-8", newline="") as fh:
        fh.write(ics_str)
    (data_dir / "state.json").write_text(
        json.dumps(new_state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (data_dir / "last_run.json").write_text(
        json.dumps(last_run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {len(windowed)} events "
        f"(merged={len(merged)}) from {len(statuses)} source(s) to {data_dir}"
    )
    return last_run


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run(args)
    except Exception as exc:  # noqa: BLE001 - CLI must fail loudly, not traceback-only
        print(f"update failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
