"""Probe 4: HC recurrence wording + BaliSquad detail structure."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

for url in [
    "https://thehoneycombers.com/bali/event/afro-thursday",
    "https://thehoneycombers.com/bali/event/salsa-bajo-el-sol",
]:
    try:
        d = requests.get(url, headers=UA, timeout=20)
        ds = BeautifulSoup(d.text, "lxml")
        log("=" * 40)
        log("HC:", url, d.status_code)
        for m in ds.find_all("meta", itemprop=True):
            if (m.get("itemprop") or "") in ("startDate", "endDate"):
                log("  meta", m.get("itemprop"), "=", m.get("content"))
        for n in ds.select(".event-category")[:4]:
            log("  cat:", n.get_text(" ", strip=True)[:120])
        body = ds.get_text(" ", strip=True)
        for pat in [r"[Ee]very\s+\w+", r"weekly", r"each\s+\w+day", r"\b(Mon|Tues?|Weds?|Thurs?|Fri|Sat|Sun)(day)?\b.{0,20}[Ee]very"]:
            ms = re.findall(pat, body)
            if ms:
                log("  recur-pat", pat, "->", ms[:6])
        i = body.lower().find("every")
        log("  'every' ctx:", body[max(0,i-120):i+160] if i >= 0 else None)
    except Exception as e:
        log("HC ERROR", url, repr(e))

# BaliSquad: listing -> full detail urls -> 2 details
try:
    d = requests.get("https://balisquad.com/event", headers=UA, timeout=20)
    ds = BeautifulSoup(d.text, "lxml")
    urls = sorted({a["href"].split("?")[0] for a in ds.find_all("a", href=True)
                   if re.match(r"^/event/.{4,}", a["href"] or "")})
    log("=" * 40)
    log("BALISQUAD list:", d.status_code, len(d.text), "detail urls:", len(urls))
    for u in urls[:12]:
        log("  -", u)
    for u in urls[2:4]:
        full = "https://balisquad.com" + u
        try:
            dd = requests.get(full, headers=UA, timeout=20)
            log("-" * 30)
            log("BS detail:", full, dd.status_code, len(dd.text))
            s2 = BeautifulSoup(dd.text, "lxml")
            h1 = s2.find("h1")
            log("  h1:", h1.get_text(" ", strip=True)[:150] if h1 else None)
            # next.js data?
            log("  __NEXT_DATA__:", bool(s2.find("script", id="__NEXT_DATA__")))
            for s in s2.find_all("script", type="application/ld+json")[:2]:
                log("  JSON-LD:", s.get_text(strip=True)[:800])
            for sel in ["time", "[class*='date']", "[class*='Date']", "[class*='venue']", "[class*='Venue']", "[class*='location']", "[class*='categor']"]:
                for n in s2.select(sel)[:4]:
                    log("  %s:" % sel, n.get_text(" ", strip=True)[:160], "| dt=", n.get("datetime"))
            body = s2.get_text(" ", strip=True)
            m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?", body)
            log("  first date-like:", m.group(0) if m else None)
        except Exception as e:
            log("BS DETAIL ERROR", full, repr(e))
except Exception as e:
    log("BS LIST ERROR", repr(e))

open("C:/code/lewagon-calendar/.logs/probe4.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe4.txt", len(out), "lines")
