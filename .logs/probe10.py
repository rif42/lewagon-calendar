"""Probe 10: BS listing card fields + organizer/area on detail."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

d = requests.get("https://balisquad.com/event", headers=UA, timeout=20)
s = BeautifulSoup(d.text, "lxml")
cards = [a for a in s.find_all("a", href=True) if re.match(r"^/event/.{4,}", a.get("href") or "")]
log("cards:", len(cards))
c = cards[1]
log("CARD HTML:", str(c)[:2500])
log("CARD TEXT:", c.get_text(" | ", strip=True)[:500])

# detail: organizer + area
d2 = requests.get("https://balisquad.com/event/bali-volleyball-academy-70cdcJ", headers=UA, timeout=20)
s2 = BeautifulSoup(d2.text, "lxml")
for n in s2.find_all(string=re.compile(r"Kerobokan")):
    log("AREA tag:", n.parent.name, n.parent.get("class"), "|", n.parent.get_text(" ", strip=True)[:150])
body = s2.get_text(" ", strip=True)
i = body.find("Hosted by")
log("HOSTED ctx:", body[i:i+200] if i >= 0 else None)
for n in s2.find_all("a", href=True):
    h = n.get("href", "")
    if "/organizer" in h or "/venues" in h or "/venue" in h:
        log("ORGLINK:", h, "|", n.get_text(" ", strip=True)[:100])
open("C:/code/lewagon-calendar/.logs/probe10.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe10.txt", len(out), "lines")
