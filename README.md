# lewagon-event-calendar — Agent Info Bank

> **For agents working on this repo.** Everything verified live on 2026-09-23
> unless marked otherwise. Canonical spec lives in the vault:
> `C:\life\Personal\Ideas\lewagon-calendar.md` (§1–§8). This README mirrors the
> parts you need to build without re-reading the whole note.

## 0. Disk state (AUDITED 2026-09-24 — read this first)

`git ls-files` in `C:\code\lewagon-calendar` returns EXACTLY these 8 tracked files.
Anything else named anywhere in this README is **[SPEC]** = design only, not on disk.

| Path | State |
|---|---|
| `README.md` | ✅ ON DISK (modified, uncommitted — `M README.md`) |
| `updater/seeds/notion_query.py` | ✅ ON DISK, committed |
| `updater/seeds/ig_scrape.py` | ✅ ON DISK, committed |
| `updater/seeds/ig_merge.py` | ✅ ON DISK, committed |
| `updater/seeds/check_dedupe.py` | ✅ ON DISK, committed |
| `updater/seeds/check_overview.py` | ✅ ON DISK, committed |
| `updater/seeds/finnsbeachclub.json` | ✅ ON DISK, committed |
| `updater/seeds/potatoheadbali.json` | ✅ ON DISK, committed |
| `updater/sources/` | ⚠️ DIRECTORY EXISTS BUT EMPTY (git tracks no files under it) |
| Everything else (`update.py`, `normalize.py`, `merge.py`, `emit_ics.py`, `requirements.txt`, all 19 `sources/*.py`, `site/`, `data/`, `events.schema.json`, `.github/workflows/`) | ❌ **[SPEC]** — spec §8.1 design only, zero code written |

In the rest of this README: **[EXISTS]** = one of the 8 files above.
**[SPEC]** = does not exist yet. If a path lacks a tag, treat it as **[SPEC]**.

## 0.1 Tech stack [SPEC — locked, nothing installed/written yet]

| Layer | Choice | Version / notes |
|---|---|---|
| Updater language | **Python** | **3.12** in Actions (`actions/setup-python@v5`); local dev on 3.11+ is fine |
| HTTP | `requests` | Timeouts 20 s per source, custom UA, `requirements.txt` [SPEC] |
| HTML parsing | `beautifulsoup4` + `lxml` | `lxml` parser for speed on 50–60 KB pages (Bandsintown, Eventbrite) |
| YAML/state | `pyyaml` | `state.json`/`last_run.json` are JSON; YAML only if config files appear later |
| Date handling | stdlib `datetime` + `zoneinfo` (`Asia/Makassar`) | No `dateutil` unless parsing gets hairy — WITA has no DST, offsets are fixed |
| ICS emit | `icalendar` package | RFC 5545 VEVENTs via lib (stable UIDs, SEQUENCE, UTC `Z`); validate output against rules in §5 |
| Actions runner | `ubuntu-latest`, 30 min timeout | `pip install -r updater/requirements.txt` per run (no browser, no Playwright) |
| Site | **Static HTML + vanilla JS** (no framework) | `fetch('./events.json')` → render week/month; FullCalendar optional — digitalbrain used FullCalendar 6.1.15 via CDN successfully, same pattern allowed |
| Site exception (user-approved) | Calendar event blocks use 8 distinct per-category hues (white text) | Off-brand by necessity — brand palette has ~4 distinguishable fills; legend in filter bar maps color→category |
| Hosting | **GitHub Pages** (deploy on push) | Data commits trigger rebuild; `events.json` baked next to `index.html` |
| Secrets | Actions secrets only (`TALLY_API_KEY` later) | Notion favolist needs NO auth. Never commit secrets; never put tokens in client JS |
| Lint/test | `python -m py_compile` (smoke) + parser asserts (§7) | No test framework mandated for MVP; each source self-validates ("≥1 dated link") |

**Explicit non-choices:** No Node in updater · No Playwright/Selenium in Actions ·
No crawl4ai server in Actions (local exploration only) · No DB (git-committed
JSON is the store) · No OAuth/Calendar API · No CSS framework mandated (keep it
light; match site to Le Wagon branding at build time).

## 1. What this is

A static website showing **Bali events in a rolling 60-day window**
(week view default, month toggle, filterable by area / category / free-vs-paid).
A GitHub Actions job re-discovers events every **3 days** (`REFRESH_DAYS`,
configurable), regenerates `data/events.json` + `data/bali-events.ics`, commits,
and GitHub Pages redeploys. Users import events into Google Calendar.

## 2. Locked decisions (do not relitigate without the user)

| # | Decision |
|---|----------|
| Import | **A + B1 + B2** (see §5 below for exact meanings) |
| Hosting | **GitHub Actions + GitHub Pages.** Cloudflare parked as fallback |
| Window | Rolling **60 days** (yesterday → +60d) |
| Views | **Weekly default**, toggleable to month |
| Categories | Music · Surf · Wellness · Food & Drink · Coworking & Tech · Arts & Culture · Nightlife (+ Other) |
| Areas | Canggu · Seminyak · Uluwatu · Ubud · Denpasar · Tabanan (+ Other) |
| Language | **English only** |
| Curation | **Tally form (link-out first)** → manual triage → curator approval; Actions-poll auto-triage later |
| Cancellations | No auto-detection for MVP; **"verify with organizer"** disclaimer on every event |
| Name | `lewagon-event-calendar` |
| Site data | **Option 1, build-time bake:** Pages build copies `data/events.json` next to `index.html`; frontend does `fetch('./events.json')`. No backend, no runtime raw-URL fetch |
| Updater lang | **Python** (`requests` + `beautifulsoup4`/`lxml`). No browser, no login, no JS in Actions |

## 3. Repo layout [SPEC] (spec §8.1 — build toward this; see §0 for what exists)

> Only `README.md`, `updater/seeds/` (7 files, see §9), and empty
> `updater/sources/` exist. Everything below marked `[TO BUILD]` = **[SPEC]**.

```text
lewagon-event-calendar/
├── .github/workflows/update.yml   # [TO BUILD] cron "0 2 */3 * *" + workflow_dispatch
├── updater/
│   ├── requirements.txt           # [TO BUILD] requests, beautifulsoup4, lxml, pyyaml, icalendar
│   ├── update.py                  # [TO BUILD] orchestrator: fetch → normalize → merge → emit
│   ├── sources/                   # [EXISTS, EMPTY] one module per source goes here
│   │   ├── notion_favolist.py     # [TO BUILD] Tier-1 (seed: updater/seeds/notion_query.py [EXISTS])
│   │   ├── baligasm.py            # [TO BUILD] Tier-1: /events + /event/<slug> details
│   │   ├── beat_bali.py           # [TO BUILD] Tier-1: cards + /events/<slug>/ details
│   │   ├── savaya.py              # [TO BUILD] Tier-1: /event-calendar + /event-calendar/<date>
│   │   ├── now_bali.py            # [TO BUILD] Tier-1: month pages + /upcoming-events/<slug>/
│   │   ├── bali_squad.py          # [TO BUILD] Tier-1: list + /event/<slug-id>
│   │   ├── bali_live.py           # [TO BUILD] Tier-1: list + /events/<slug>
│   │   ├── eventbrite.py          # [TO BUILD] Tier-2: /events--this-week/, /free--events/
│   │   ├── discotech.py           # [TO BUILD] Tier-2: list + /events/<id>-<slug>
│   │   ├── meetup.py              # [TO BUILD] Tier-2: /find/id--<area>/ × Canggu/Ubud/Denpasar
│   │   ├── bandsintown.py         # [TO BUILD] Tier-2: city page + /e/<id>-<slug>, parse selectively
│   │   ├── whatsnew_indo.py       # [TO BUILD] Tier-2: hotel/F&B promos
│   │   ├── atlas.py               # [TO BUILD] Tier-2: /beach-club/event + /event/<slug>
│   │   ├── surf_calendar.py       # [TO BUILD] Tier-2: calendar.asiansurf.co + /event/<slug>
│   │   ├── bali_com.py            # [TO BUILD] Tier-2 WEEKLIES ONLY (static-ish)
│   │   ├── elkabron.py            # [TO BUILD] Tier-2 WEEKLIES ONLY (recurring series)
│   │   ├── gov_coe.py             # [TO BUILD] Tier-3 watchlist, monthly
│   │   └── tally.py               # [TO BUILD] Tier-1 poll (LATER; manual triage until API key exists)
│   ├── normalize.py               # [TO BUILD] → canonical event (uid, UTC dates, area, category)
│   ├── merge.py                   # [TO BUILD] JSON-state merge (see §7 — NOT markdown regexes)
│   ├── emit_ics.py                # [TO BUILD] events.json + bali-events.ics from ONE merged list
│   └── seeds/                     # [EXISTS] verified starting points (see §9)
├── site/index.html + assets/      # [TO BUILD] week default / month toggle / filters / A+B2 header / B1 per card
├── data/                          # [TO BUILD] events.json, bali-events.ics, state.json, last_run.json (committed)
└── events.schema.json             # [TO BUILD]
```

**Tier cadence:** Tier-1 every run · Tier-2 when day-of-month even · Tier-3 on day 1.
`workflow_dispatch` input `tier` overrides (`1`, `1+2`, `all`, `auto`).

## 4. Data flow [SPEC] (§8.6 — the core guarantee; no code written yet)

```text
sources/*.py → normalize → merge (state.json) → data/events.json ─┐
                                              → data/bali-events.ics │ SAME merged list
                                              → data/last_run.json ─┘
commit (ALWAYS, even on failure) → Pages rebuild → fresh site
```

- **Guarantee 1:** JSON (app) and ICS (Subscribe feed) come from the same
  in-memory merged list in one run — site and feed can never disagree.
- **Guarantee 2:** `state.json` (seen UIDs + SEQUENCE) is the merge memory.
  New → append; changed → update + SEQUENCE+1; missing 2 consecutive runs →
  `status: stale` (kept 1 run, then dropped). Never delete on a single bad run.
- **Keep-alive:** every run commits (data or at least `last_run.json`), which
  counts as repo activity and defeats the 60-day scheduled-workflow auto-disable.
- **Dead-man signal:** `last_run.json.ran_at` older than `REFRESH_DAYS + 2` →
  badge red + Actions email.

## 5. Google Calendar import [SPEC] (A + B1 + B2 — exact semantics, no code yet)

- **Button A — "Subscribe (auto-updates, ~1 day delay)"** — feed header only.
  User: GCal → Other calendars (+) → From URL → paste `bali-events.ics` URL.
  Auto-updates BUT Google refreshes feeds every **12–24h** (no force-refresh).
  ICS rules: stable UIDs (`sha1(source|norm_title|start_utc)`), SEQUENCE bumps,
  UTC `Z` times (Bali = WITA, UTC+8, no DST), valid RFC 5545, warn if >500 KB.
  Line endings MUST be CRLF — Google rejects LF-only feeds ("unable to subscribe").
- **Button B1 — "Add this event (opens Google Calendar)"** — every event card.
  Template link, **no file download**: click → GCal tab prefilled → Save.
  `https://calendar.google.com/calendar/render?action=TEMPLATE&text=…&dates=START/END&details=…&location=…`
  Static copy (moves/cancels don't propagate); embed source URL in `details`;
  URL-encode everything; all-day = date format (`20261005/20261006`).
- **Button B2 — "Download .ics snapshot (Settings → Import)"** — feed header only.
  Template links are single-event; batch "add all" inherently needs a file:
  download → GCal Settings → Import & export → Import. One-time 60-day snapshot.
- **Rejected:** per-user OAuth + Calendar API (app verification, token storage —
  revisit only with accounts/RSVP).
- UI copy: A = "auto-updates, up to ~24h delay" · B1 = "instant, won't update if
  the event changes" · B2 = "one-time copy of the next 60 days, won't update".

## 6. Sources — verified matrix [RESEARCH, no parser code yet] (all live-tested 2026-09-23)

### Tier-1 (every run)

| Source | URL pattern | What you get | Parse notes |
|---|---|---|---|
| Notion favolist | `POST favolist.notion.site/api/v3/queryCollection` (no auth) | 61 rows: name, datetime (WITA), type, location/event URLs, cost | **Query UNFILTERED** (`"filters": []`, limit 5000), filter dates locally — the date-filter combo returns 0 rows. Rows at `recordMap.block[id].value.value.properties` (DOUBLE `value`). `title`=name, `fja;`=datetime (`\u2023`+`d` annot, `start_date`/`end_date`), `hP[[`=type, `~xjM`=loc URL, `PMXu`=event URL, `fWMC`=cost. Seed: `seeds/notion_query.py` |
| Baligasm | `baligasm.com/events` → `/event/<slug>` | 26 events, area + Upcoming/Week/Month filters; detail = exact date/time, street address, geo, ticket link | Best-structured headliner source. ⚠️ SHARED OPERATOR with Guideline (images on `thebaliguideline.com`, `?utm_source=thebaliguideline`) — **one origin for corroboration, never double-confirm across them** |
| Beat Bali | `thebeatbali.com/bali-events/` → `/events/<slug>/` | **Nightlife backbone.** Nightly dated cards (name/day/time/venue + detail) | ~32k chars, server-rendered |
| Savaya direct | `savaya.com/event-calendar` → `/event-calendar/<month-day-year>` | Club headliners at source (Full Moon, Bodzin, Martinez Bros…) | ~55k chars, server-rendered |
| NOW! Bali | `nowbali.co.id/all-events/?month=<M>` → `/upcoming-events/<slug>/` | Dated events + categories; month + category filters | Server-rendered WP |
| BaliSquad | `balisquad.com/event` → `/event/<slug-id>` | 127 events w/ statuses (Cancelled, spots-left); has own Add Event form | Nomad/community layer |
| Bali.live | `bali.live/events` → `/events/<slug>`; `?types=` filters | Typed cards (Party/Music/Health…) map to our categories | District + venue per card |

### Tier-2 (day-of-month even)

| Source | URL pattern | What you get | Parse notes |
|---|---|---|---|
| Eventbrite | `eventbrite.com/d/indonesia--bali--…/events--this-week/` (+ `/free--events/`) | Grassroots: dinners, yoga, salsa, tech meetups | ~43–61k chars |
| Discotech | `app.discotech.me/bali/events` → `/events/<id>-<slug>` | Day-grouped; guestlist/ticket/VIP flags; corroborates Beat | `?page=2` for more |
| Meetup | `meetup.com/find/id--<canggu\|ubud\|denpasar>/` | Dated WITA events (thin: 2–3 featured/area) + group layer (recurring series) | 8k chars/area |
| Bandsintown | `bandsintown.com/c/bali-indonesia` (+ `/this-week/`) → `/e/<id>-<slug>` | Touring concerts; Today/Week/Month/genre filters | ~50k chars, heavy markup — parse selectively |
| What's New Indo | `whatsnewindonesia.com/event/bali` | Hotel/F&B promos (dated cards) — layer nothing else has | ~28k chars |
| Atlas | `atlasbeachfest.com/beach-club/event` → `/event/<slug>` | Biggest beach club's own calendar (NYE w/ Quavo, Disko Afrika…) | ~13k chars |
| Surf calendar | `calendar.asiansurf.co` → `/event/<slug>` | Dated/statused comps (CONFIRMED/TENTATIVE) — anchors Surf category | ~5k chars, has status field |
| bali.com | `bali.com/events-calendar/`, `/nightlife/` | Perennial guides → **WEEKLIES ONLY** (FINNS, Old Man's, Savaya, La Favela) | Few dated events; cache aggressively |
| El Kabron | `elkabron.com/<party>` pages | Recurring series ("Every Saturday") → **WEEKLIES ONLY** | List page is JS-shell; no dated instances |

### Tier-3 (monthly) / Rejected

- **Govt CoE** (`lovebali.baliprov.go.id/...CoE-2026...`): 56-event editorial,
  month granularity — watchlist only, confirm exact dates via search.
- **REJECTED (do not add):** nomads.com (login wall, 0 event rows headless) ·
  allevents.in Bali (Jakarta events pollute the page — untrustworthy geo) ·
  me-ticket.com (502 bot-wall) · ra.co + nomeo.co (bot-wall/CF; stealth-browser
  only) · Songkick (duplicates Bandsintown) · Guideline list page (JS shell —
  use Baligasm instead, same pool, server-rendered; harvest real detail slugs,
  never guess — a guessed Savaya slug 404'd).

### Dedup priority (one event = one entry, prefer ticket-link source)

Club headliners → Savaya-direct/Baligasm, corroborate Discotech + Bandsintown ·
Nightly parties → Beat first, Discotech second · Community/nomad → Squad first,
Meetup second · Grassroots → Eventbrite · Dining/culture → NOW! Bali · Official
culture/sport → Govt watchlist.

## 7. Per-source contract [SPEC] (spec §8.3 — applies when writing `sources/*.py`)

- Expose `fetch() -> list[RawEvent]`; **never throw past the orchestrator.**
- Own try/except, own 20 s timeout, own User-Agent, 1–2 s politeness sleep.
- On failure: log, set `state.json["sources"][name] = {status: "error", …}`,
  return `[]` (run continues on last-good data).
- **Parser assert:** "list page yielded ≥1 dated link" — else `error` status
  (a redesign pages you instead of silently emptying the feed).
- `requests` + `bs4`/`lxml` only. No browser, no login, no JS.
- New source ≈ 50 lines following this contract + one row in the §6 table.

## 8. Canonical event + normalize rules [SPEC] (spec §8.4 — `normalize.py` not written)

- Fields: `uid`, `name`, `location`, `description`, `start_utc`, `finish_utc`,
  `area`, `category`, `cost`, `free` (bool), `source_url`, `source` (module name),
  `discovered_at`, `last_seen_at`, `sequence`, `status`
  (`confirmed`/`needs_review`/`stale`/`cancelled`).
- `uid = sha1(source|norm_title|start_utc)` — stable across runs (Google dedupes on it).
- Dates: parse WITA (UTC+8, no DST, `Asia/Makassar`) → emit UTC `Z`.
  All-day/multi-day per RFC 5545.
- Area map: Canggu · Seminyak · Uluwatu · Ubud · Denpasar · Tabanan · Other
  (match venue strings; "Canggu area"-vague → Other + flag `needs_review`).
- Category map: Music · Surf · Wellness · Food & Drink · Coworking & Tech ·
  Arts & Culture · Nightlife · Other.
- Tally submissions enter as `status: needs_review`; curator flips to `confirmed`.
- Hygiene: link back to source; no scraped poster art without rights; no ticket
  resell claims; every event shows "verify with organizer".

## 9. Seeds in this directory [EXISTS] (the only code on disk — audited §0)

| File | Status | Notes for agents |
|---|---|---|
| `seeds/notion_query.py` | ✅ VERIFIED 2026-09-23 (61 rows, re-verified after move) | Base `sources/notion_favolist.py` on this. Wrap `txt()`/`dat()` + unfiltered query into `fetch()`; add field mapping per §6 |
| `seeds/ig_scrape.py` + `ig_merge.py` | ⚠️ PARKED (from digitalbrain) | Needs `instaloader==4.14.2` + throwaway IG login (anon = instant 429). `ig_merge.py` has a **known dedupe-regex bug**: expects `- **Start:**` / `## N)` / `## Overview — Dated Events`, but the real file uses `## 11)` + `## Overview (…)` + table rows with no `Start:` fields — name/date dedupe is dead, Overview append silently skipped. Do NOT reuse as-is; merge against JSON state (§4) |
| `seeds/finnsbeachclub.json`, `potatoheadbali.json` | Fixtures for the IG PoC | Offline test data (2 candidates + 1 non-candidate each) |
| `seeds/check_dedupe.py`, `check_overview.py` | Audit probes | How the `merge.py` bug was proven (0 keys on a 13-event file). Reusable pattern for testing future parsers |

## 10. Environment notes (learned the hard way 2026-09-23)

- **Sandbox:** file ops outside the workspace need approval; `pip install` fails
  (temp-dir writes blocked) — workaround used: download the `.whl` via urllib,
  rename to `.zip`, `Expand-Archive` into a local dir, `PYTHONPATH` it. In
  Actions this is irrelevant (`pip install -r requirements.txt` works normally).
- **PowerShell quoting:** complex `python -c` one-liners break — write small
  `.py` files with the `write` tool and run those instead.
- **Console encoding:** `cp1252` chokes on `→`/`—`/`✅` in stdout — redirect to
  files and `read` them, or accept mojibake in logs (files are unaffected).
- **crawl4ai server** (vault machine): `http://127.0.0.1:11235`, start via
  `C:\life\tmp\crawl4ai-server\start-server.ps1`, health at `/health`. Local
  exploration only — NOT part of the Actions design.
- **Secrets seen during research:** digitalbrain's `.env` holds a throwaway IG
  password + Cloudflare R2 keys in its working tree (gitignored but present).
  **Rotate before any public push. Never copy secrets into this repo.**

## 11. Build order [SPEC] (spec §7 — nothing below is on disk except seeds)

1. `events.schema.json` → 2. `update.py` + `normalize.py` + `merge.py` +
   `emit_ics.py` → 3. Tier-1 sources (notion, baligasm, beat, savaya, now,
   squad, live) → 4. Tier-2 → 5. Tier-3 → 6. `update.yml` + Pages deploy →
   7. `site/` frontend → 8. Tally form + link-out button → 9. health badge.
