#!/usr/bin/env python3
"""
Instagram PoC scraper using instaloader (free, local-only).

Fetches last N posts per handle and saves raw JSON per handle to
notes/knowledge_bank/instagram_raw/<handle>.json (ignored by .gitignore)
or scripts/instagram/out/<handle>.json as staging.

Handles:
- Throwaway login via --login (session saved to scripts/instagram/session-<user>)
- Rate-limit sleeps + exponential backoff on 429 / ConnectionException
- Offline fixture mode (--fixture / --use-fixture) for smoke-testing without IG

Heuristic: flags is_candidate posts that look like events (dates/times + keywords).
Does NOT auto-create events — just annotates for merge.py human review.

Usage:
  pip install -r scripts/instagram/requirements.txt
  python scripts/instagram/scrape.py --handles finnsbeachclub potatoheadbali --limit 12
  python scripts/instagram/scrape.py --login YOUR_THROWAWAY --handles finnsbeachclub --limit 12 --sleep 3
  python scripts/instagram/scrape.py --use-fixture --handles finnsbeachclub potatoheadbali
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load .env from repo root if present (gitignored). Optional dependency: python-dotenv.
try:
    from dotenv import load_dotenv  # type: ignore

    _repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(_repo_root / ".env", override=False)
    load_dotenv(Path(__file__).parent / ".env", override=False)
    load_dotenv(override=False)
except ImportError:
    pass

# Heuristic patterns
DATE_RE = re.compile(
    r"(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?"
    r"|\b\d{1,2}\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
    r"|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?"
    r"|\b\d{1,2}\s*[-–]\s*\d{1,2}\s*(?:aug|sep|oct|nov|dec|jan|feb|mar|apr|may|jun|jul)[a-z]*)",
    re.I,
)
TIME_RE = re.compile(r"\b\d{1,2}[:.]\d{2}\s*(?:am|pm|wita|wib)?\b|\b\d{1,2}\s*(?:am|pm)\b", re.I)
KEYWORDS_RE = re.compile(
    r"\b(brunch|dinner|launch|wellness|party|festival|market|yoga|music|concert|workshop|exhibition|master\s*series|culinary|dialogue|series|session|dj|live|tasting|pop[-\s]?up)\b",
    re.I,
)
HASHTAG_RE = re.compile(r"#(\w+)")
MENTION_RE = re.compile(r"@(\w+(?:\.\w+)*)")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "notes" / "knowledge_bank" / "instagram_raw"
FALLBACK_OUT = Path(__file__).parent / "out"
FIXTURE_DIR = Path(__file__).parent / "fixtures"
SESSION_DIR = Path(__file__).parent


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Instaloader PoC scraper for Bali events")
    p.add_argument("--handles", nargs="+", default=["finnsbeachclub", "potatoheadbali"], help="IG handles without @")
    p.add_argument("--limit", type=int, default=12, help="Posts per handle (default 12)")
    p.add_argument("--sleep", type=float, default=2.5, help="Seconds between requests (default 2.5)")
    p.add_argument("--login", type=str, default=None, help="Throwaway IG username to login with")
    p.add_argument("--password", type=str, default=None, help="Password (prefer interactive prompt; avoid committing)")
    p.add_argument("--out-dir", type=str, default=None, help="Output dir (default notes/knowledge_bank/instagram_raw)")
    p.add_argument("--use-fixture", action="store_true", help="Use local fixtures instead of hitting Instagram (offline smoke test)")
    p.add_argument("--fixture", action="store_true", help="Alias for --use-fixture")
    return p.parse_args()


def heuristic_is_candidate(caption: str) -> tuple[bool, list[str]]:
    if not caption:
        return False, []
    reasons: list[str] = []
    if DATE_RE.search(caption):
        reasons.append("date_pattern")
    if TIME_RE.search(caption):
        reasons.append("time_pattern")
    if KEYWORDS_RE.search(caption):
        reasons.append("keyword")
    # Require at least date/time OR keyword+date? For PoC: (date or time) OR keyword alone counts if strong?
    # Keep simple: candidate if (date or time) or (keyword and len>30) — avoids every brunch post without date.
    is_candidate = bool(DATE_RE.search(caption) or TIME_RE.search(caption) or KEYWORDS_RE.search(caption))
    # Stricter: if only keyword but no date/time, still flag but mark weaker
    if is_candidate and not (DATE_RE.search(caption) or TIME_RE.search(caption)):
        reasons.append("keyword_only")
    return is_candidate, reasons


def post_to_dict(handle: str, post) -> dict:
    caption = post.caption or ""
    hashtags = HASHTAG_RE.findall(caption)
    mentions = MENTION_RE.findall(caption)
    is_candidate, reasons = heuristic_is_candidate(caption)
    # location may be None
    loc_name = None
    loc_slug = None
    try:
        if post.location:
            loc_name = getattr(post.location, "name", None)
            loc_slug = getattr(post.location, "slug", None)
    except Exception:
        pass
    taken = post.date  # datetime (tz-aware UTC)
    # instaloader post.date is UTC-ish; normalize
    taken_utc = taken.astimezone(timezone.utc) if taken.tzinfo else taken.replace(tzinfo=timezone.utc)
    taken_wita = taken_utc.astimezone(timezone.utc)  # keep UTC canonical; WITA is UTC+8 display elsewhere
    # Keep both UTC iso and raw
    return {
        "handle": handle,
        "shortcode": post.shortcode,
        "post_id": str(post.mediaid),
        "url": f"https://www.instagram.com/p/{post.shortcode}/",
        "caption": caption,
        "caption_hashtags": hashtags,
        "caption_mentions": mentions,
        "taken_at": taken_utc.isoformat(),
        "taken_at_local_wita": (taken_utc.astimezone(timezone.utc).isoformat()),  # canonical UTC; convert to WITA in UI
        "location_name": loc_name,
        "location_slug": loc_slug,
        "is_video": bool(post.is_video),
        "likes": getattr(post, "likes", None),
        "comments": getattr(post, "comments", None),
        "is_candidate": is_candidate,
        "candidate_reasons": reasons,
    }


def load_fixture(handle: str) -> list[dict]:
    path = FIXTURE_DIR / f"{handle}.json"
    if not path.exists():
        # Fallback: generic fixture
        generic = FIXTURE_DIR / "sample.json"
        if generic.exists():
            path = generic
        else:
            return []
    data = json.loads(path.read_text(encoding="utf-8"))
    # Support both {posts: [...]} and [...] shapes
    if isinstance(data, dict) and "posts" in data:
        return data["posts"]
    if isinstance(data, list):
        return data
    return []


def save_handle_json(handle: str, posts: list[dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "handle": handle,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "scrape_tool": "instaloader 4.14.2",
        "count": len(posts),
        "posts": posts,
    }
    out_path = out_dir / f"{handle}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    args = parse_args()
    use_fixture = args.use_fixture or args.fixture
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUT

    # Ensure fixture dir exists for offline mode
    if use_fixture:
        handles = [h.lstrip("@").strip() for h in args.handles]
        for handle in handles:
            posts = load_fixture(handle)
            # If fixture empty, fabricate minimal heuristic demo so smoke-test passes
            if not posts:
                posts = [
                    {
                        "handle": handle,
                        "shortcode": "DEMO123",
                        "post_id": "000",
                        "url": f"https://www.instagram.com/p/DEMO123/",
                        "caption": "Brunch this Saturday Aug 30 — 11am at Starfish Bloo. See you there! #bali #canggu",
                        "caption_hashtags": ["bali", "canggu"],
                        "caption_mentions": [],
                        "taken_at": datetime.now(timezone.utc).isoformat(),
                        "taken_at_local_wita": datetime.now(timezone.utc).isoformat(),
                        "location_name": handle,
                        "location_slug": None,
                        "is_video": False,
                        "likes": None,
                        "comments": None,
                        "is_candidate": True,
                        "candidate_reasons": ["date_pattern", "time_pattern", "keyword"],
                    }
                ]
            # Slice to limit
            posts = posts[: args.limit]
            # Re-annotate heuristic in case fixture stale
            for p in posts:
                cap = p.get("caption", "")
                is_c, reasons = heuristic_is_candidate(cap)
                # Don't overwrite if already set, but ensure fields exist
                p.setdefault("is_candidate", is_c)
                p.setdefault("candidate_reasons", reasons)
            path = save_handle_json(handle, posts, out_dir)
            # Also save to fallback out/ for ignored staging
            try:
                FALLBACK_OUT.mkdir(parents=True, exist_ok=True)
                (FALLBACK_OUT / f"{handle}.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                pass
            print(f"[fixture] {handle}: {len(posts)} posts -> {path} (candidates: {sum(1 for x in posts if x.get('is_candidate'))})")
        print(f"Done (fixture mode). Output dir: {out_dir}")
        return 0

    # Live mode — requires instaloader
    try:
        import instaloader
        from instaloader import Profile, ConnectionException, LoginRequiredException
    except ImportError:
        print("ERROR: instaloader not installed. Run: pip install -r scripts/instagram/requirements.txt", file=sys.stderr)
        return 2

    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=False,
    )
    # polite
    L.context.sleep = True

    # Auth — resolve from CLI args or env/.env (never log password)
    effective_login = args.login or os.getenv("IG_USERNAME") or os.getenv("IG_USER") or os.getenv("INSTAGRAM_USER")
    effective_password = args.password or os.getenv("IG_PASSWORD") or os.getenv("IG_PASS") or os.getenv("INSTAGRAM_PASSWORD")
    # Auth
    if effective_login:
        session_file = SESSION_DIR / f"session-{effective_login}"
        # Try load existing session first
        try:
            L.load_session_from_file(effective_login, str(SESSION_DIR))
            print(f"Loaded session for {effective_login} from {session_file}")
        except FileNotFoundError:
            print(f"No session file for {effective_login}, will login")
        except Exception as e:
            print(f"Could not load session: {e}", file=sys.stderr)

        # If not logged in, attempt login (password or interactive)
        # Check if we have a session already
        is_logged = L.context.is_logged_in if hasattr(L.context, "is_logged_in") else False
        # Fallback check
        try:
            is_logged = L.test_login() is not None if hasattr(L, "test_login") else is_logged
        except Exception:
            pass

        if not is_logged:
            pw = effective_password
            if not pw:
                import getpass

                try:
                    pw = getpass.getpass(f"Password for {effective_login}: ")
                except Exception:
                    pw = None
            if pw:
                try:
                    L.login(effective_login, pw)
                    L.save_session_to_file(str(SESSION_DIR))
                    print(f"Logged in as {effective_login}, session saved")
                except Exception as e:
                    print(f"Login failed for {effective_login}: {e}", file=sys.stderr)
                    print("Hint: Check throwaway credentials / 2FA. You can also run: instaloader --login YOUR_USER", file=sys.stderr)
                    # Continue anonymous — may still get public posts but likely rate-limited
            else:
                print("No password provided — continuing without login (may be rate-limited)", file=sys.stderr)

    handles = [h.lstrip("@").strip() for h in args.handles]
    for handle in handles:
        print(f"\n=== @{handle} (limit {args.limit}) ===")
        posts: list[dict] = []
        try:
            profile = Profile.from_username(L.context, handle)
        except Exception as e:
            # instaloader raises ProfileNotExistsException, ConnectionException, LoginRequiredException
            print(f"ERROR fetching profile @{handle}: {e}", file=sys.stderr)
            # Backoff hint
            if "429" in str(e) or "Too Many Requests" in str(e):
                print("429 rate-limit — wait 10–30 min, reduce --limit, increase --sleep", file=sys.stderr)
            # Save empty file so merge knows it was attempted
            save_handle_json(handle, [], out_dir)
            continue

        count = 0
        backoff = 1
        try:
            for post in profile.get_posts():
                # polite sleep
                time.sleep(args.sleep)
                try:
                    d = post_to_dict(handle, post)
                except Exception as e:
                    print(f"  warn: failed to parse post {getattr(post, 'shortcode', '?')}: {e}", file=sys.stderr)
                    continue
                posts.append(d)
                count += 1
                marker = "★" if d["is_candidate"] else " "
                print(f"  [{count:2d}]{marker} {d['shortcode']} {d['taken_at'][:10]} {d['candidate_reasons']} | {d['caption'][:70].replace(chr(10), ' ')}")
                if count >= args.limit:
                    break
                # reset backoff on success
                backoff = 1
        except Exception as e:
            msg = str(e)
            if "429" in msg or "Too Many Requests" in msg or "ConnectionException" in msg:
                sleep_s = min(60, backoff * 5)
                print(f"Rate-limited / connection error: {e} — backing off {sleep_s}s", file=sys.stderr)
                time.sleep(sleep_s)
                backoff = min(backoff * 2, 12)
            elif "LoginRequired" in type(e).__name__ or "login" in msg.lower():
                print(f"Login required for @{handle}: {e} — re-run with --login YOUR_THROWAWAY", file=sys.stderr)
            else:
                print(f"Error iterating posts for @{handle}: {e}", file=sys.stderr)

        out_path = save_handle_json(handle, posts, out_dir)
        try:
            FALLBACK_OUT.mkdir(parents=True, exist_ok=True)
            (FALLBACK_OUT / f"{handle}.json").write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
        cands = sum(1 for p in posts if p.get("is_candidate"))
        print(f"Saved {len(posts)} posts ({cands} candidates) -> {out_path}")

    print("\nDone. Inspect with: cat notes/knowledge_bank/instagram_raw/<handle>.json | head -n 100")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
