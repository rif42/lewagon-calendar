"""Probe 9: BS detail date/time + venue + description selectors precisely."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

for url in [
    "https://balisquad.com/event/bali-volleyball-academy-70cdcJ",
    "https://balisquad.com/event/bali-baza-aT9lhv",
]:
    d = requests.get(url, headers=UA, timeout=20)
    s = BeautifulSoup(d.text, "lxml")
    log("=" * 40)
    log("URL:", url, d.status_code)
    h1 = s.find("h1")
    log("h1:", h1.get_text(" ", strip=True)[:120] if h1 else None)
    # date line: p.font-semibold.text-lg containing weekday
    for p in s.find_all("p", class_=re.compile(r"font-semibold")):
        t = p.get_text(" ", strip=True)
        if re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)", t):
            sib = p.find_next_sibling("p")
            log("DATE:", t[:120], "| NEXT:", (sib.get_text(" ", strip=True)[:120] if sib else None))
    # venue link
    for a in s.find_all("a", href=re.compile(r"/(organizer|venue|community|communities)")):
        log("VENLINK:", a.get("href"), "|", a.get_text(" ", strip=True)[:100])
    # category chips: a.rounded-lg.px-3
    for a in s.find_all("a", class_=re.compile(r"rounded-lg")):
        log("CHIP:", a.get("href"), "|", a.get_text(" ", strip=True)[:80])
    # description block: longest <p> or div
    paras = [(len(p.get_text(" ", strip=True)), p.get_text(" ", strip=True)[:300]) for p in s.find_all("p")]
    paras.sort(reverse=True)
    log("LONGEST P:", paras[0][1] if paras else None)
    # cancelled/status?
    body = s.get_text(" ", strip=True)
    for w in ["cancelled", "canceled", "sold out", "full", "spots left"]:
        if w in body.lower():
            i = body.lower().find(w)
            log("STATUSWORD:", w, "->", body[max(0,i-60):i+80])
open("C:/code/lewagon-calendar/.logs/probe9.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe9.txt", len(out), "lines")
