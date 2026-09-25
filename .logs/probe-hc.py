"""Probe Honeycombers calendar structure live."""
import re, sys
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []

def log(*a):
    line = " ".join(str(x) for x in a)
    out.append(line)

for url in [
    "https://thehoneycombers.com/bali/calendar/",
    "https://thehoneycombers.com/bali/calendar/this-week/",
    "https://thehoneycombers.com/bali/calendar/this-month/",
]:
    try:
        r = requests.get(url, headers=UA, timeout=20)
        log("URL:", url, "->", r.status_code, len(r.text), "bytes")
        if r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        ev_links = set()
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if "/bali/event/" in h:
                h = h.split("?")[0].rstrip("/")
                ev_links.add(h if h.startswith("http") else "https://thehoneycombers.com" + h if h.startswith("/") else h)
        log("  /bali/event/ anchors:", len(ev_links))
        for l in sorted(ev_links)[:10]:
            log("   -", l)
    except Exception as e:
        log("URL:", url, "ERROR", repr(e))

# fetch one detail page
try:
    r = requests.get("https://thehoneycombers.com/bali/calendar/", headers=UA, timeout=20)
    soup = BeautifulSoup(r.text, "lxml")
    first = None
    for a in soup.find_all("a", href=True):
        if "/bali/event/" in a["href"]:
            h = a["href"].split("?")[0].rstrip("/")
            first = h if h.startswith("http") else "https://thehoneycombers.com" + h
            break
    log("FIRST DETAIL:", first)
    if first:
        d = requests.get(first, headers=UA, timeout=20)
        log("detail ->", d.status_code, len(d.text), "bytes")
        ds = BeautifulSoup(d.text, "lxml")
        # schema.org meta
        for m in ds.find_all("meta", itemprop=True):
            if m.get("itemprop") in ("startDate", "endDate", "name"):
                log("  meta[itemprop=%s] content=%s" % (m.get("itemprop"), m.get("content")))
        for tag in ds.find_all(attrs={"itemprop": True}):
            ip = tag.get("itemprop")
            if ip in ("name", "address", "price", "startDate", "endDate", "description", "location"):
                log("  <%s itemprop=%s> %s" % (tag.name, ip, tag.get_text(" ", strip=True)[:200] or tag.get("content", "")))
        # title
        log("  <title>:", ds.title.get_text(strip=True)[:200] if ds.title else None)
        h1 = ds.find("h1")
        log("  <h1>:", h1.get_text(" ", strip=True)[:200] if h1 else None)
        # date-ish text
        body = ds.get_text(" ", strip=True)
        m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\d{4}?", body)
        log("  first date-like text:", m.group(0) if m else None)
        # json-ld
        for s in ds.find_all("script", type="application/ld+json"):
            log("  JSON-LD:", s.get_text(strip=True)[:1500])
except Exception as e:
    log("DETAIL ERROR", repr(e))

open("C:/code/lewagon-calendar/.logs/probe-hc.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out)[:6000])
