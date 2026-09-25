"""Probe 8: raw BS Event JSON-LD (no unicode_escape) + listing text sample."""
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

d = requests.get("https://balisquad.com/event/bali-volleyball-academy-70cdcJ", headers=UA, timeout=20)
i = d.text.find('"@type":"Event"')
log("Event idx:", i)
if i > 0:
    # walk back to opening brace
    j = d.text.rfind("{", 0, i - 60)
    log("RAW:", d.text[j:j+1800])
d2 = requests.get("https://balisquad.com/event", headers=UA, timeout=20)
k = d2.text.find("Beach Volleyball")
log("LISTING ctx:", d2.text[max(0,k-500):k+800] if k > 0 else None)
open("C:/code/lewagon-calendar/.logs/probe8.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe8.txt", len(out), "lines")
