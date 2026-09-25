import re, itertools
html = open(r"C:\code\lewagon-calendar\.task\probe_detail.html", encoding="utf-8").read()
def show(pat, n=8):
    print("=== PAT:", pat)
    for m in itertools.islice(re.finditer(pat, html, re.S), n):
        print("   ", re.sub(r"\s+", " ", m.group(0))[:280])
show(r'.{80}[Dd]ate.{0,120}')
show(r'.{60}event-date.{0,200}')
show(r'.{60}[Vv]enue.{0,150}')
show(r'.{60}[Cc]ategor.{0,150}')
show(r'.{0,80}\d{1,2} (October|September|November) 2026.{0,80}')
classes = sorted(set(re.findall(r'class="([^"]{0,100})"', html)))
print("N classes:", len(classes))
for c in classes:
    if any(k in c.lower() for k in ("date","event","venue","location","time","meta","detail","post","calendar")):
        print("  CLS:", c)
show(r'"@type":"Event".{0,600}', 3)
show(r'startDate.{0,120}', 5)
show(r'.{120}2[01]\d\d-[01]\d-[0-3]\d.{0,60}', 15)
