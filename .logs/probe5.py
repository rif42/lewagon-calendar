"""Probe 5: BaliSquad detail date/venue/category selectors + HC weekly context."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

url = "https://balisquad.com/event/bali-volleyball-academy-70cdcJ"
d = requests.get(url, headers=UA, timeout=20)
s = BeautifulSoup(d.text, "lxml")
body = s.get_text("\n", strip=True)
# find date context lines
lines = [l.strip() for l in body.split("\n") if l.strip()]
log("TOTAL lines:", len(lines))
for i, l in enumerate(lines):
    if re.search(r"(Sept|Oct|2026|PM|AM|WITA|Volleyball|Berawa|Canggu|price|IDR|Free)", l, re.I):
        log("L%d: %s" % (i, l[:200]))
    if i > 0 and len(out) > 60:
        break
log("=" * 30)
# dump elements containing 'September 25'
for n in s.find_all(string=re.compile(r"September 25")):
    p = n.parent
    for _ in range(3):
        if p is None:
            break
        log("CTX tag:", p.name, (p.get("class") or ""), "|", p.get_text(" ", strip=True)[:250])
        p = p.parent
    log("-" * 20)
    if len(out) > 100:
        break
open("C:/code/lewagon-calendar/.logs/probe5.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe5.txt", len(out), "lines")
