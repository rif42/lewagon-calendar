"""Probe 6: BS venue/category element classes + HC weekly context."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

d = requests.get("https://balisquad.com/event/bali-volleyball-academy-70cdcJ", headers=UA, timeout=20)
s = BeautifulSoup(d.text, "lxml")
# venue: find strings with BVA / Academy and show tag+class
for n in s.find_all(string=re.compile(r"Bali Volleyball Academy \(BVA\)")):
    p = n.parent
    log("VENUE tag:", p.name, p.get("class"), "|", p.get_text(" ", strip=True)[:150])
    if len([l for l in out if l.startswith("VENUE")]) > 3:
        break
# category chips: look for links/badges with sport etc
for a in s.find_all("a", href=True):
    h = a.get("href", "")
    if "/category" in h or "/tag" in h or "/explore" in h:
        log("CATLINK:", h, "|", a.get_text(" ", strip=True)[:80])
for n in s.find_all(string=re.compile(r"(?i)^(sport|wellness|music|food|community|social|outdoor|fitness)$")):
    log("CATCHIP:", n.parent.name, n.parent.get("class"), "|", n.strip())
body = s.get_text(" ", strip=True)
i = body.find("Volleyball Social Games")
log("ADDR ctx:", body[i:i+600] if i >= 0 else None)

# HC afro-thursday weekly context
d2 = requests.get("https://thehoneycombers.com/bali/event/afro-thursday", headers=UA, timeout=20)
s2 = BeautifulSoup(d2.text, "lxml")
body2 = s2.get_text(" ", strip=True)
j = body2.lower().find("weekly")
log("HC weekly ctx:", body2[max(0, j-300):j+300] if j >= 0 else None)
for m in s2.find_all("meta", itemprop=True):
    if (m.get("itemprop") or "") in ("startDate", "endDate", "description"):
        log("HC meta", m.get("itemprop"), "=", (m.get("content") or "")[:300])
open("C:/code/lewagon-calendar/.logs/probe6.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe6.txt", len(out), "lines")
