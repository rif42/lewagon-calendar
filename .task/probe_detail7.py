import re, requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36 lewagon-event-calendar/1.0 (+https://nowbali.co.id)"}
slugs = ["ready-to-be-seen-n-1/", "potato-head-presents-dekmantel/", "padma-musical-series-george-harliono-hera-hyesang-park/", "samatra-quiet-gestures/", "an-evening-of-purpose-possibility/"]
for s in slugs:
    try:
        r = requests.get("https://www.nowbali.co.id/upcoming-events/" + s, headers=UA, timeout=20)
        h = r.text
        i = h.find("post-entry")
        ctx = re.sub(r"\s+", " ", h[max(0,i-200):i+700])
        art = re.search(r'<article[^>]*class="([^"]*)"', h)
        open(r"C:\code\lewagon-calendar\.task\out6.txt", "a", encoding="utf-8", errors="replace").write("\n==== " + s + " (" + str(len(h)) + ") ====\nARTICLE-CLASS: " + (art.group(1) if art else "?") + "\n" + ctx + "\n")
    except Exception as e:
        open(r"C:\code\lewagon-calendar\.task\out6.txt", "a", encoding="utf-8", errors="replace").write("\n==== " + s + " FAIL " + repr(e) + "\n")
