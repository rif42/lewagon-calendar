"""Probe 2: HC listing card structure + category labels + more details; NOW!Bali + BaliSquad reachability."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

# --- HC listing card structure ---
r = requests.get("https://thehoneycombers.com/bali/calendar/", headers=UA, timeout=20)
soup = BeautifulSoup(r.text, "lxml")
anchors = []
seen = set()
for a in soup.find_all("a", href=True):
    h = a["href"].split("?")[0].rstrip("/")
    if "/bali/event/" in h and h not in seen:
        seen.add(h)
        anchors.append(a)
log("HC cards:", len(anchors))
first = anchors[0]
log("FIRST CARD HTML:", str(first)[:3000])
log("FIRST CARD TEXT:", first.get_text(" | ", strip=True)[:800])
# look for category-ish labels near cards
log("--- second card ---")
if len(anchors) > 1:
    log("SECOND CARD HTML:", str(anchors[1])[:3000])

# --- HC detail: category + venue block on 3 samples ---
for url in [
    "https://thehoneycombers.com/bali/event/salsa-bajo-el-sol",
    "https://thehoneycombers.com/bali/event/purnama-sound-meditation-dinner-september-2026",
    "https://thehoneycombers.com/bali/event/caviar-dinner-at-mozaic-ubud",
]:
    try:
        d = requests.get(url, headers=UA, timeout=20)
        log("=" * 40)
        log("DETAIL:", url, d.status_code)
        ds = BeautifulSoup(d.text, "lxml")
        for m in ds.find_all("meta", itemprop=True):
            if (m.get("itemprop") or "") in ("startDate", "endDate", "name", "description"):
                log("  meta", m.get("itemprop"), "=", (m.get("content") or "")[:250])
        loc = ds.find(attrs={"itemprop": "location"})
        log("  location block:", loc.get_text(" | ", strip=True)[:400] if loc else None)
        # category links / tags
        for sel in ["a[rel='tag']", ".event-category", ".tribe-events-event-categories"]:
            for n in ds.select(sel)[:6]:
                log("  tag(%s):" % sel, n.get_text(" ", strip=True)[:120])
        # breadcrumb often has category
        bc = ds.select_one(".breadcrumb, nav.breadcrumb, [class*='breadcrumb']")
        log("  breadcrumb:", bc.get_text(" > ", strip=True)[:300] if bc else None)
        h1 = ds.find("h1")
        log("  h1:", h1.get_text(" ", strip=True)[:150] if h1 else None)
    except Exception as e:
        log("DETAIL ERROR", url, repr(e))

# --- NOW!Bali ---
for url in [
    "https://nowbali.co.id/all-events/?month=9",
    "https://nowbali.co.id/all-events/?month=10",
]:
    try:
        d = requests.get(url, headers=UA, timeout=20)
        log("=" * 40)
        log("NOWBALI:", url, d.status_code, len(d.text))
        ds = BeautifulSoup(d.text, "lxml")
        ups = set()
        for a in ds.find_all("a", href=True):
            if "/upcoming-events/" in a["href"]:
                ups.add(a["href"].split("?")[0])
        log("  /upcoming-events/ anchors:", len(ups))
        for u in sorted(ups)[:8]:
            log("   -", u)
    except Exception as e:
        log("NOWBALI ERROR", url, repr(e))

# --- BaliSquad ---
for url in ["https://balisquad.com/event"]:
    try:
        d = requests.get(url, headers=UA, timeout=20)
        log("=" * 40)
        log("BALISQUAD:", url, d.status_code, len(d.text))
        ds = BeautifulSoup(d.text, "lxml")
        evs = set()
        for a in ds.find_all("a", href=True):
            if re.search(r"/event/.+", a["href"]):
                evs.add(a["href"].split("?")[0])
        log("  /event/<slug> anchors:", len(evs))
        for u in sorted(evs)[:8]:
            log("   -", u)
    except Exception as e:
        log("BALISQUAD ERROR", url, repr(e))

open("C:/code/lewagon-calendar/.logs/probe2.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe2.txt", len(out), "lines")
