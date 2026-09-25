"""Probe 13: escaped Event JSON-LD fields."""
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

d = requests.get("https://balisquad.com/event/bali-volleyball-academy-70cdcJ", headers=UA, timeout=20)
i = d.text.find('@type')
log("plain @type idx:", i)
j = d.text.find('Event', i)
seg = d.text[max(0, i-300):i+2500]
open("C:/code/lewagon-calendar/.logs/probe13-seg.txt", "w", encoding="utf-8").write(seg)
for field in ["startDate", "endDate", "location", "eventStatus", "offers", "price", "description", "address"]:
    k = d.text.find(field, i)
    if k > 0:
        log(field, "->", d.text[k:k+300].replace("\\n", " ")[:300])
    else:
        log(field, "-> NOT FOUND")
open("C:/code/lewagon-calendar/.logs/probe13.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe13")
