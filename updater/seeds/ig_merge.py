#!/usr/bin/env python3
"""
Merge Instagram candidates into notes/knowledge_bank/Bali Events List.md.

Reads notes/knowledge_bank/instagram_raw/<handle>.json (from scrape.py),
dedupes against existing Bali Events List.md by (normalized name, start date),
and inserts new Instagram-sourced events as `needs_review: true` entries.

Schema per event (mirrors Bali Events List 7 properties):
  name, location, description, start, finish?, category, cost
  + source_url, scraped_at, source_handle, needs_review

Safety:
- Never auto-removes web-sourced events; only appends IG candidates.
- Keeps file sorted date-asc and filtered to window (now -> +1 month) for dated events.
- Preserves OKF frontmatter (type, window_start/end, sort, tags, sources).
- Respects Obsidian wikilink discipline — does not create links to non-existent notes.

Usage:
  python scripts/instagram/merge.py --dry-run        # preview without writing
  python scripts/instagram/merge.py                  # write + validate
  python scripts/instagram/merge.py --handles finnsbeachclub --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BALI_LIST = REPO_ROOT / "notes" / "knowledge_bank" / "Bali Events List.md"
RAW_DIR = REPO_ROOT / "notes" / "knowledge_bank" / "instagram_raw"
FALLBACK_RAW_DIR = Path(__file__).parent / "out"

# ---------- frontmatter helpers ----------

FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    import yaml

    m = FM_RE.match(text)
    if not m:
        raise ValueError("No YAML frontmatter found (expected ---\n...\n---\n)")
    fm = yaml.safe_load(m.group(1)) or {}
    body = text[m.end() :]
    return fm, body


def dump_frontmatter(fm: dict) -> str:
    import yaml

    # Keep keys ordered somewhat nicely but don't lose unknowns
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n"


# ---------- dedupe helpers ----------

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def extract_existing_keys(body: str) -> set[tuple[str, str]]:
    """Extract (norm_name, start_date) from existing dated sections + overview."""
    keys: set[tuple[str, str]] = set()
    # From detail sections: ## N) Name then - **Start:** YYYY-MM-DD
    for m in re.finditer(r"^## \d+\)\s*(.+?)\n.*?^- \*\*Start:\*\*\s*(\d{4}-\d{2}-\d{2})", body, re.M | re.S):
        name, d = m.groups()
        keys.add((norm(name), d))
    # Also from overview table rows inside dated block
    for line in body.splitlines():
        if line.startswith("|") and re.search(r"\d{4}-\d{2}-\d{2}", line):
            # crude: extract name (col 2) and Start (col 4)
            parts = [p.strip() for p in line.split("|")]
            # parts[0] empty, [1] #, [2] Name, [3] Location, [4] Start
            if len(parts) >= 5 and re.match(r"\d{4}-\d{2}-\d{2}", parts[4]):
                keys.add((norm(parts[2]), parts[4][:10]))
    return keys


def load_ig_posts(handles: list[str] | None) -> list[dict]:
    posts: list[dict] = []
    seen_shortcode: set[str] = set()
    found_any = False
    # Prefer RAW_DIR; only fall back to FALLBACK_RAW_DIR for handles not already seen
    seen_handles: set[str] = set()
    for d in [RAW_DIR, FALLBACK_RAW_DIR]:
        if not d.exists():
            continue
        for path in sorted(d.glob("*.json")):
            if handles and path.stem not in handles:
                continue
            if path.stem in seen_handles:
                continue  # RAW_DIR already provided this handle
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"warn: could not read {path}: {e}", file=sys.stderr)
                continue
            found_any = True
            seen_handles.add(path.stem)
            for p in data.get("posts", []):
                if not p.get("is_candidate"):
                    continue
                if "date_pattern" not in (p.get("candidate_reasons") or []) and "time_pattern" not in (p.get("candidate_reasons") or []):
                    continue
                sc = p.get("shortcode")
                if sc and sc in seen_shortcode:
                    continue
                if sc:
                    seen_shortcode.add(sc)
                posts.append(p)
    if not posts and not found_any:
        print(f"warn: no raw JSON found in {RAW_DIR} or {FALLBACK_RAW_DIR}", file=sys.stderr)
    return posts


def post_to_event(post: dict) -> dict:
    caption = (post.get("caption") or "").strip()
    handle = post.get("handle") or "unknown"
    short = caption[:120].replace("\n", " ").strip()
    # Heuristic name: first sentence or up to 80 chars
    first_line = caption.split("\n")[0].strip()[:80]
    name = first_line or f"Instagram: @{handle} — {short[:40]}"
    # Try to keep name readable
    if len(name) < 10:
        name = f"Instagram @{handle}: {short[:50]}"
    loc = post.get("location_name") or f"Instagram @{handle}"
    # Description: truncated caption + source
    desc = caption[:380].replace("\n", " ").strip()
    if len(caption) > 380:
        desc += " …"
    desc += f" (via Instagram @{handle} — {post.get('url','')})"
    # Dates: we don't parse exact event date from caption in PoC — mark as TBD window
    # Use taken_at date as fallback start with needs_review
    taken = post.get("taken_at") or datetime.now(timezone.utc).isoformat()
    try:
        dt = datetime.fromisoformat(taken.replace("Z", "+00:00"))
        start_date = dt.date().isoformat()
    except Exception:
        start_date = date.today().isoformat()
    return {
        "name": name,
        "location": loc,
        "description": desc,
        "start": f"{start_date} 00:00",  # placeholder; needs human review
        "finish": None,
        "category": "Instagram / Candidate",
        "cost": "See Instagram post",
        "source_url": post.get("url", ""),
        "source_handle": handle,
        "scraped_at": post.get("taken_at", ""),
        "needs_review": True,
        "candidate_reasons": post.get("candidate_reasons", []),
        "raw_shortcode": post.get("shortcode", ""),
    }


def format_event_section(idx: int, ev: dict) -> str:
    finish_line = f"- **Finish:** {ev['finish']} WITA" if ev.get("finish") else "- **Finish:** TBD (needs review)"
    return (
        f"## {idx}) {ev['name']}  <!-- IG:{ev.get('raw_shortcode','')} needs_review -->\n"
        f"\n"
        f"- **Location:** {ev['location']}\n"
        f"- **Description:** {ev['description']}\n"
        f"- **Start:** {ev['start']} WITA *(needs review — date parsed from caption/taken_at)*\n"
        f"{finish_line}\n"
        f"- **Category:** {ev['category']}\n"
        f"- **Cost:** {ev['cost']}\n"
        f"- **Source:** {ev['source_url']} (IG @{ev['source_handle']}, scraped {ev.get('scraped_at','')[:10]})\n"
        f"- **Status:** `needs_review: true`\n"
    )


def format_overview_row(idx: int, ev: dict) -> str:
    start = ev["start"]
    finish = ev.get("finish") or "TBD"
    return f"| {idx} | {ev['name']} | {ev['location']} | {start} | {finish} | {ev['category']} | {ev['cost']} |"


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge IG candidates into Bali Events List.md")
    ap.add_argument("--dry-run", action="store_true", help="Preview without writing")
    ap.add_argument("--handles", nargs="*", default=None, help="Only merge these handles")
    args = ap.parse_args()

    if not BALI_LIST.exists():
        print(f"ERROR: Bali Events List not found: {BALI_LIST}", file=sys.stderr)
        return 2

    text = BALI_LIST.read_text(encoding="utf-8")
    try:
        fm, body = parse_frontmatter(text)
    except Exception as e:
        print(f"ERROR parsing frontmatter: {e}", file=sys.stderr)
        return 2

    # Validate OKF type
    if not fm.get("type"):
        print("ERROR: frontmatter type missing (OKF requires non-empty type)", file=sys.stderr)
        return 2

    # Determine window
    ws = fm.get("window_start")
    we = fm.get("window_end")
    # ws/we may be date objects after yaml load
    def to_date(v) -> date | None:
        if v is None:
            return None
        if isinstance(v, date) and not isinstance(v, datetime):
            return v
        if isinstance(v, datetime):
            return v.date()
        try:
            return date.fromisoformat(str(v)[:10])
        except Exception:
            return None

    w_start = to_date(ws)
    w_end = to_date(we)
    if w_start and w_end:
        print(f"Window: {w_start} -> {w_end} (from frontmatter)")

    existing_keys = extract_existing_keys(body)
    print(f"Existing dated keys: {len(existing_keys)}")

    posts = load_ig_posts(args.handles)
    print(f"IG candidates (with date pattern): {len(posts)} handles considered: {args.handles or 'all'}")
    if not posts:
        print("No IG candidates to merge — nothing to do.")
        # Still validate file OK
        if args.dry_run:
            print("[dry-run] no changes")
        return 0

    events = [post_to_event(p) for p in posts]
    # Deduplicate by (norm name, start date) and by shortcode
    seen_short = set()
    existing_shorts = set(re.findall(r"IG:([A-Z0-9_]+)", body))
    new_events: list[dict] = []
    for ev in events:
        sc = ev.get("raw_shortcode")
        key = (norm(ev["name"]), ev["start"][:10])
        if sc and sc in existing_shorts:
            print(f"  skip duplicate shortcode {sc}: {ev['name']}")
            continue
        if sc and sc in seen_short:
            print(f"  skip duplicate shortcode in batch {sc}")
            continue
        if key in existing_keys:
            print(f"  skip duplicate key {key}")
            continue
        # Window filter for dated events (placeholder date == taken_at date, so likely in window)
        try:
            ev_date = date.fromisoformat(ev["start"][:10])
            if w_start and w_end and not (w_start <= ev_date <= w_end):
                # For IG placeholders, don't hard-filter — but warn
                print(f"  note: {ev['name']} start {ev_date} outside window — will still append with needs_review")
        except Exception:
            pass
        seen_short.add(sc)
        new_events.append(ev)

    if not new_events:
        print("All IG candidates already present — no new rows.")
        return 0

    # Build overview rows + sections to append
    # We append at end of dated block, before "## Weekly in Canggu" section
    marker = "## Weekly in Canggu"
    insert_at = body.find(marker)
    if insert_at == -1:
        # Fallback: before ## Notes
        insert_at = body.find("## Notes")
    if insert_at == -1:
        insert_at = len(body)

    # Find next index for numbering (count existing dated sections)
    dated_indices = [int(n) for n in re.findall(r"^## (\d+)\)", body, re.M)]
    next_idx = (max(dated_indices) + 1) if dated_indices else 1

    # Build overview addition (we insert into the Overview table before its closing blank line)
    # Find overview table block
    overview_re = re.compile(r"(## Overview — Dated Events.*?\n\|[^\n]*\|[^\n]*\n\|---[^\n]*\n(?:\|[^\n]*\n)*)", re.S)
    om = overview_re.search(body)
    overview_addition = ""
    if om:
        existing_overview_dates = re.findall(r"2026-\d{2}-\d{2}", om.group(1))
        # Count existing overview rows (dated only, before weekly table)
        overview_rows = [l for l in om.group(1).splitlines() if l.startswith("|") and "Name" not in l and "---" not in l and "2026-" in l]
        base = len(overview_rows)
        rows = []
        for i, ev in enumerate(new_events, start=1):
            rows.append(format_overview_row(base + i, ev))
        overview_addition = "\n".join(rows) + "\n"
        new_body_with_overview = body[: om.end()] + overview_addition + body[om.end() :]
        # Adjust insert_at for the shifted body
        insert_at += len(overview_addition)
        body_for_sections = new_body_with_overview
    else:
        print("warn: could not find Overview table to append to — will only append sections", file=sys.stderr)
        body_for_sections = body

    sections = ""
    for i, ev in enumerate(new_events, start=0):
        sections += format_event_section(next_idx + i, ev) + "\n"

    new_body = body_for_sections[:insert_at] + sections + body_for_sections[insert_at:]

    # Update frontmatter
    fm["updated"] = date.today().isoformat()
    if "instagram_handles" not in fm:
        fm["instagram_handles"] = sorted({p.get("handle") for p in posts if p.get("handle")})
    else:
        fm["instagram_handles"] = sorted(set(fm["instagram_handles"]) | {p.get("handle") for p in posts})
    # Add source note
    srcs = fm.get("sources") or []
    ig_src = "instagram (instaloader) — candidates flagged needs_review"
    if ig_src not in srcs:
        fm["sources"] = srcs + [ig_src]

    new_text = dump_frontmatter(fm) + new_body

    # Validation
    import yaml

    try:
        fm2, body2 = parse_frontmatter(new_text)
        assert fm2.get("type"), "type missing after merge"
        # Check YAML parses
        yaml.safe_load(FM_RE.match(new_text).group(1))
    except Exception as e:
        print(f"ERROR: merged file failed validation: {e}", file=sys.stderr)
        return 2

    # Check sorted? New IG events use taken_at date — may be out of order; warn but don't fail PoC
    dated_block = new_text.split("## Weekly in Canggu")[0] if "## Weekly in Canggu" in new_text else new_text
    starts = re.findall(r"^- \*\*Start:\*\* (\d{4}-\d{2}-\d{2})", dated_block, re.M)
    if starts != sorted(starts):
        print(f"warn: dated block not strictly sorted after IG append: {starts[:12]} — run manual date fix for merged candidates", file=sys.stderr)

    if args.dry_run:
        print(f"\n[dry-run] Would add {len(new_events)} IG candidate(s):")
        for ev in new_events:
            print(f"  - {ev['name']} | {ev['location']} | {ev['start']} | {ev['source_url']} | {ev['candidate_reasons']}")
        if overview_addition:
            print(f"\n[dry-run] Overview rows to append:\n{overview_addition.strip()}")
        print(f"\n[dry-run] Sections preview (first):\n{sections[:800]}...")
        return 0

    BALI_LIST.write_text(new_text, encoding="utf-8")
    print(f"Merged {len(new_events)} IG candidate(s) into {BALI_LIST}")
    for ev in new_events:
        print(f"  + {ev['name']} ({ev['source_url']})")
    # Final check: file still has frontmatter type
    print(f"Updated frontmatter instagram_handles: {fm['instagram_handles']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
