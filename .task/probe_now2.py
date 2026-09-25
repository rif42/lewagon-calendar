import requests, re
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36 lewagon-event-calendar/1.0 (+https://nowbali.co.id)"}
for url in ["https://nowbali.co.id/all-events/?month=September", "https://nowbali.co.id/all-events/?month=October"]:
    try:
        r = requests.get(url, headers=UA, timeout=20)
        print(url, r.status_code, len(r.text))
        hrefs = sorted(set(re.findall(r'href="([^"]*upcoming-events/[^"]*)"', r.text)))
        print("  upcoming-events links:", len(hrefs))
        for h in hrefs:
            print("   ", h)
        open(r"C:\code\lewagon-calendar\.task\probe_%s.html" % url.split("month=")[-1], "w", encoding="utf-8").write(r.text)
    except Exception as e:
        print(url, "FAIL", repr(e))

# detail page probe
durl = "https://www.nowbali.co.id/upcoming-events/uwrf-2026/"
try:
    r = requests.get(durl, headers=UA, timeout=20)
    print(durl, r.status_code, len(r.text))
    open(r"C:\code\lewagon-calendar\.task\probe_detail.html", "w", encoding="utf-8").write(r.text)
    print(r.text[:3000])
except Exception as e:
    print("detail FAIL", repr(e))
