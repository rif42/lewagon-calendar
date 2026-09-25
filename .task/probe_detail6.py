import re
lst = open(r"C:\code\lewagon-calendar\.task\probe_October.html", encoding="utf-8").read()
arts = re.findall(r'<article[^>]*>.*?</article>', lst, re.S)
a = re.sub(r"\n\s*", "\n", arts[0])
open(r"C:\code\lewagon-calendar\.task\out5.txt", "w", encoding="utf-8", errors="replace").write(a[:4000])
# detail pages for each Oct slug: fetch date/venue/category lines
import requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36 lewagon-event-calendar/1.0 (+https://nowbali.co.id)"}
slugs = ["amici-presents-an-exclusive-evening-with-chef-enrico-bartolini/", "uwrf-2026/", "steps-of-hope-breast-cancer-charity-walk/", "ignite-2026/"]
for s in slugs:
    try:
        r = requests.get("https://www.nowbali.co.id/upcoming-events/" + s, headers=UA, timeout=20)
        h = r.text
        i = h.find("fw-bold fs-6")
        ctx = re.sub(r"\s+", " ", h[max(0,i-200):i+800])
        cats = sorted(set(re.findall(r'event-category/([^"/]+)', h)))
        open(r"C:\code\lewagon-calendar\.task\out5.txt", "a", encoding="utf-8", errors="replace").write("\n==== " + s + " (" + str(len(h)) + ") ====\n" + ctx + "\nCATS-in-page: " + ",".join(cats) + "\n")
    except Exception as e:
        open(r"C:\code\lewagon-calendar\.task\out5.txt", "a", encoding="utf-8", errors="replace").write("\n==== " + s + " FAIL " + repr(e) + "\n")
