"""Probe 15: detail venue anchor across 4 events + card venue part parsing."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

for url in [
    "https://balisquad.com/event/bukitsocial-IZ427w",
    "https://balisquad.com/event/mana-uluwatu-xnKCUr",
    "https://balisquad.com/event/learningbahasainbali-OVTcNf",
    "https://balisquad.com/event/desa-potato-head-bali-wuMfCo",
]:
    d = requests.get(url, headers=UA, timeout=20)
    s = BeautifulSoup(d.text, "lxml")
    log("=" * 40)
    log("URL:", url)
    h1 = s.find("h1")
    log("h1:", h1.get_text(" ", strip=True)[:80] if h1 else None)
    for a in s.select("a.text-lg"):
        log("A.text-lg:", a.get("href"), "|", a.get_text(" ", strip=True)[:100])
    m = re.search(r'\\\\"location\\\\":\{\\\\"@type\\\\":\\\\"Place\\\\",\\\\"name\\\\":\\\\"([^"\\\\]+)', d.text)
    log("LD place:", m.group(1) if m else None)
open("C:/code/lewagon-calendar/.logs/probe15.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe15")
