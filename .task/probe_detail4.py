import re
html = open(r"C:\code\lewagon-calendar\.task\probe_detail.html", encoding="utf-8").read()
i = html.find("21 October 2026")
ctx = re.sub(r"\s+", " ", html[max(0,i-2500):i+2500])
lst = open(r"C:\code\lewagon-calendar\.task\probe_October.html", encoding="utf-8").read()
j = lst.find("upcoming-events/")
ctx2 = re.sub(r"\s+", " ", lst[max(0,j-1500):j+3000])
open(r"C:\code\lewagon-calendar\.task\out3b.txt", "w", encoding="utf-8", errors="replace").write(ctx + "\n" + "="*100 + "\n" + ctx2)
# also extract time/location/category bits
for pat in [r'event-category/[^"]+', r'<li class="fs-5[^<]*<a[^>]*>[^<]*</a>', r'fw-bold fs-6.{0,200}', r'pb-3 fs-6.{0,200}', r'(?i)(wellness|yoga|dining|food|music|nightlife|party|dj|club)[^<]{0,60}']:
    pass
cats = sorted(set(re.findall(r'event-category/[^"]+', html)))
open(r"C:\code\lewagon-calendar\.task\out3c.txt", "w", encoding="utf-8").write("CATS: " + "\n".join(cats) + "\n")
