"""Probe 3: NOW!Bali detail structure + month-filter variants."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

# month filter variants
for url in [
    "https://www.nowbali.co.id/all-events/?month=october",
    "https://www.nowbali.co.id/all-events/?month=10",
    "https://nowbali.co.id/all-events/",
]:
    try:
        d = requests.get(url, headers=UA, timeout=20)
        ds = BeautifulSoup(d.text, "lxml")
        ups = sorted({a["href"].split("?")[0] for a in ds.find_all("a", href=True) if "/upcoming-events/" in a["href"]})
        log("LIST:", url, d.status_code, len(d.text), "anchors:", len(ups))
    except Exception as e:
        log("LIST ERROR", url, repr(e))

# detail structure x2
for url in [
    "https://www.nowbali.co.id/upcoming-events/padma-musical-series-george-harliono-hera-hyesang-park/",
    "https://www.nowbali.co.id/upcoming-events/steps-of-hope-breast-cancer-charity-walk/",
]:
    try:
        d = requests.get(url, headers=UA, timeout=20)
        log("=" * 40)
        log("DETAIL:", url, d.status_code, len(d.text))
        ds = BeautifulSoup(d.text, "lxml")
        h1 = ds.find("h1")
        log("  h1:", h1.get_text(" ", strip=True)[:150] if h1 else None)
        # date/time-ish elements
        for sel in [".event-date", ".event_time", ".tribe-event-date-start", "time",
                    "[class*='event-date']", "[class*='event_date']", "[class*='date-time']"]:
            for n in ds.select(sel)[:4]:
                log("  %s:" % sel, n.get_text(" ", strip=True)[:160], "| dt=", n.get("datetime"))
        # category-ish
        for sel in ["a[rel='tag']", "[class*='categor']", "[class*='event-cat']"]:
            for n in ds.select(sel)[:6]:
                log("  %s:" % sel, n.get_text(" ", strip=True)[:120])
        # venue-ish
        for sel in ["[class*='venue']", "[class*='location']", ".event-venue"]:
            for n in ds.select(sel)[:4]:
                log("  %s:" % sel, n.get_text(" ", strip=True)[:200])
        # json-ld
        for s in ds.find_all("script", type="application/ld+json"):
            log("  JSON-LD:", s.get_text(strip=True)[:1200])
        body = ds.get_text(" ", strip=True)
        m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?", body)
        log("  first date-like:", m.group(0) if m else None)
    except Exception as e:
        log("DETAIL ERROR", url, repr(e))

open("C:/code/lewagon-calendar/.logs/probe3.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe3.txt", len(out), "lines")
