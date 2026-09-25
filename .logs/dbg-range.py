"""Debug: why range-block finish didn't attach."""
import sys
sys.path.insert(0, "C:/code/lewagon-calendar/updater/sources")
import honeycombers, requests

s = requests.Session()
s.headers.update(honeycombers.HEADERS)
html = honeycombers._get(s, "https://thehoneycombers.com/bali/event/atomic-17/")
from bs4 import BeautifulSoup
soup = BeautifulSoup(html, "lxml")
ev = honeycombers._parse_detail(html, "https://thehoneycombers.com/bali/event/atomic-17/")
print("start:", ev["start"], "finish:", ev["finish"])
page_text = soup.get_text(" ", strip=True)
import re
i = page_text.find("Dates")
print("CTX:", page_text[i:i+120] if i >= 0 else "NO Dates block")
