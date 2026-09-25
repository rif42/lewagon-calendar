import re, itertools, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
html = open(r"C:\code\lewagon-calendar\.task\probe_detail.html", encoding="utf-8").read()
i = html.find("21 October 2026")
print(re.sub(r"\s+", " ", html[max(0,i-2500):i+2500]))
print("="*100)
lst = open(r"C:\code\lewagon-calendar\.task\probe_October.html", encoding="utf-8").read()
j = lst.find("upcoming-events/")
print(re.sub(r"\s+", " ", lst[max(0,j-1500):j+3000]))
