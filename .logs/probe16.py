"""Probe 16: are the 4 stale HC pages recurring series? check date + recur words."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

for url in [
    "https://thehoneycombers.com/bali/event/atomic-17/",
    "https://thehoneycombers.com/bali/event/cascayu-promotion/",
    "https://thehoneycombers.com/bali/event/mooncake-for-the-mid-autumn-festival/",
    "https://thehoneycombers.com/bali/event/blue-peaceful-frequency-a-collective-art-exhibition/",
]:
    d = requests.get(url, headers=UA, timeout=20)
    s = BeautifulSoup(d.text, "lxml")
    log("=" * 40)
    log("URL:", url.split("/event/")[1])
    for m in s.find_all("meta", itemprop=True):
        if (m.get("itemprop") or "") in ("startDate", "endDate", "description"):
            log("  meta", m.get("itemprop"), "=", (m.get("content") or "")[:280])
    body = s.get_text(" ", strip=True)
    for pat in [r"[Ee]very\s+\w+", r"until\s+\w+", r"through\s+\w+", r"\b(daily|weekly|weekends?)\b",
                r"(September|October|November|December)\s+\d{1,2}"]:
        ms = re.findall(pat, body)
        if ms:
            log("  pat", pat, "->", ms[:8])
open("C:/code/lewagon-calendar/.logs/probe16.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe16")
