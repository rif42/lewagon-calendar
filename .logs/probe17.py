"""Probe 17: full description text of the stale promos for run-date phrasing."""
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 lewagon-probe/1.0"}
out = []
def log(*a):
    out.append(" ".join(str(x) for x in a))

for url in [
    "https://thehoneycombers.com/bali/event/atomic-17/",
    "https://thehoneycombers.com/bali/event/blue-peaceful-frequency-a-collective-art-exhibition/",
    "https://thehoneycombers.com/bali/event/mooncake-for-the-mid-autumn-festival/",
]:
    d = requests.get(url, headers=UA, timeout=20)
    s = BeautifulSoup(d.text, "lxml")
    m = s.find("meta", attrs={"itemprop": "description"})
    log("=" * 40)
    log("URL:", url.split("/event/")[1])
    log("DESC:", (m.get("content") or "")[:900] if m else None)
    # also visible Date block
    body = s.get_text(" ", strip=True)
    i = body.find("Date")
    log("DATEBLOCK:", body[i:i+250] if i >= 0 else None)
open("C:/code/lewagon-calendar/.logs/probe17.txt", "w", encoding="utf-8").write("\n".join(out))
print("wrote probe17")
