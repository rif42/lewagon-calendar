import re
html = open(r"C:\code\lewagon-calendar\.task\probe_detail.html", encoding="utf-8").read()
i = html.find("fw-bold fs-6")
ctx = re.sub(r"\s+", " ", html[max(0,i-500):i+3000])
open(r"C:\code\lewagon-calendar\.task\out4.txt", "w", encoding="utf-8", errors="replace").write(ctx + "\n====\n")
# listing: extract all article blocks info
lst = open(r"C:\code\lewagon-calendar\.task\probe_October.html", encoding="utf-8").read()
arts = re.findall(r'<article[^>]*>(.*?)</article>', lst, re.S)
lines = []
for a in arts:
    a1 = re.sub(r"\s+", " ", a)
    title = re.search(r'title="([^"]+)"', a1)
    date = re.search(r'(\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d(?:\s*-\s*\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d)?)', a1)
    venue = re.search(r'fa-location-dot.{0,200}?>([^<]+)', a1)
    cat = re.search(r'event-category/[^/]+/"[^>]*>([^<]+)', a1)
    href = re.search(r'href="([^"]*upcoming-events/[^"]*)"', a1)
    lines.append("T=%s | D=%s | V=%s | C=%s | U=%s" % (title.group(1)[:60] if title else "?", date.group(1) if date else "?", venue.group(1) if venue else "?", cat.group(1).strip() if cat else "?", href.group(1) if href else "?"))
open(r"C:\code\lewagon-calendar\.task\out4.txt", "a", encoding="utf-8", errors="replace").write("\n".join(lines))
# sept too
lst2 = open(r"C:\code\lewagon-calendar\.task\probe_September.html", encoding="utf-8").read()
arts2 = re.findall(r'<article[^>]*>(.*?)</article>', lst2, re.S)
lines2 = []
for a in arts2:
    a1 = re.sub(r"\s+", " ", a)
    title = re.search(r'title="([^"]+)"', a1)
    date = re.search(r'(\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d(?:\s*-\s*\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d)?)', a1)
    href = re.search(r'href="([^"]*upcoming-events/[^"]*)"', a1)
    lines2.append("T=%s | D=%s | U=%s" % (title.group(1)[:60] if title else "?", date.group(1) if date else "?", href.group(1) if href else "?"))
open(r"C:\code\lewagon-calendar\.task\out4.txt", "a", encoding="utf-8", errors="replace").write("\n==== SEPT ====\n" + "\n".join(lines2))
