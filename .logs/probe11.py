"""Probe 11: decode BS embedded Event JSON-LD fully."""
import re, json
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

d = requests.get("https://balisquad.com/event/bali-volleyball-academy-70cdcJ", headers=UA, timeout=20)
i = d.text.find('"@type":"Event"')
# find full escaped payload: search for startDate nearby
j = d.text.find("startDate", i)
log("startDate ctx:", d.text[j-200:j+400] if j > 0 else None)
k = d.text.find("location", i)
log("location ctx:", d.text[k-100:k+600] if k > 0 else None)
m = re.search(r'"eventStatus":"([^"\\]+)"', d.text[i:i+3000])
log("eventStatus:", m.group(1) if m else None)
m2 = re.search(r'"offers":(\{[^}]*\}|\[[^\]]*\])', d.text[i:i+3000])
log("offers:", m2.group(1)[:400] if m2 else None)
open("C:/code/lewagon-calendar/.logs/probe11.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe11.txt", len(out), "lines")
