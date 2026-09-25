"""Probe 7: BS Event JSON-LD extraction + listing card dates."""
import re, json
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

d = requests.get("https://balisquad.com/event/bali-volleyball-academy-70cdcJ", headers=UA, timeout=20)
# find Event JSON-LD inside next_f scripts
m = re.search(r'\{"@context":"https://schema\.org","@type":"Event".*?\}(?=")', d.text)
log("Event JSON-LD regex hit:", bool(m))
if m:
    raw = m.group(0).encode().decode("unicode_escape", errors="ignore")
    log("decoded:", raw[:2500])
# listing: check date text on cards
d2 = requests.get("https://balisquad.com/event", headers=UA, timeout=20)
s2 = BeautifulSoup(d2.text, "lxml")
body = s2.get_text(" ", strip=True)
log("listing has dates:", re.findall(r"(September|October)\s+\d{1,2},?\s*2026", body)[:10])
open("C:/code/lewagon-calendar/.logs/probe7.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe7.txt", len(out), "lines")
