"""Probe 14: extract escaped startDate/endDate/location exactly."""
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

d = requests.get("https://balisquad.com/event/bali-volleyball-academy-70cdcJ", headers=UA, timeout=20)
t = d.text
for pat in [
    r'\\"startDate\\":\\"([^"\\]+)',
    r'\\"endDate\\":\\"([^"\\]+)',
    r'\\"location\\":\{\\"@type\\":\\"Place\\",\\"name\\":\\"([^"\\]+)',
    r'streetAddress\\":\\"([^"\\]*)\\"',
    r'addressLocality\\":\\"([^"\\]*)\\"',
    r'"name":"Place".{0,80}?name.{0,5}?([^,]{0,80})',
]:
    m = re.search(pat, t)
    log(pat[:40], "->", m.group(1)[:200] if m else None)
i = t.find("PostalAddress")
log("postal ctx:", t[i-100:i+500] if i > 0 else None)
open("C:/code/lewagon-calendar/.logs/probe14.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe14")
