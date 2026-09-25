import requests, re
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36 lewagon-event-calendar/1.0 (+https://nowbali.co.id)"}
for url in ["https://nowbali.co.id/all-events/?month=9", "https://nowbali.co.id/all-events/?month=10", "https://nowbali.co.id/all-events/"]:
    try:
        r = requests.get(url, headers=UA, timeout=20)
        print(url, r.status_code, len(r.text))
        open(r"C:\code\lewagon-calendar\.task\probe_%s.html" % url.split("month=")[-1].replace("/","_").replace("?","q"), "w", encoding="utf-8").write(r.text)
        hrefs = sorted(set(re.findall(r'href="([^"]*upcoming-events/[^"]*)"', r.text)))
        print("  upcoming-events links:", len(hrefs))
        for h in hrefs[:15]:
            print("   ", h)
        hrefs2 = sorted(set(re.findall(r'href="([^"]*event[^"]*)"', r.text)))[:40]
        print("  event-ish links sample:", len(hrefs2))
        # month filter links?
        m = sorted(set(re.findall(r'href="([^"]*month[^"]*)"', r.text)))[:10]
        print("  month links:", m)
    except Exception as e:
        print(url, "FAIL", repr(e))
