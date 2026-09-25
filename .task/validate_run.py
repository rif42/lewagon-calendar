import json, re, collections
d = json.load(open(r"C:\code\lewagon-calendar\data\events.json", encoding="utf-8"))
sch = json.load(open(r"C:\code\lewagon-calendar\events.schema.json", encoding="utf-8"))
print("TOTAL:", len(d))
print("BY-CAT:", dict(collections.Counter(e.get("category") for e in d)))
print("BY-SRC:", dict(collections.Counter(e.get("source") for e in d)))
# schema-lite checks
req = sch["required"]; enums = {"area": sch["properties"]["area"]["enum"], "category": sch["properties"]["category"]["enum"], "status": sch["properties"]["status"]["enum"]}
bad = 0
uids = set()
for e in d:
    for f in req:
        if f not in e: print("MISSING", f, e.get("uid")); bad += 1
    if e.get("area") not in enums["area"]: print("BAD-AREA", e.get("area"), e.get("uid")); bad += 1
    if e.get("category") not in enums["category"]: print("BAD-CAT", e.get("category"), e.get("uid")); bad += 1
    if e.get("status") not in enums["status"]: print("BAD-STATUS", e.get("status"), e.get("uid")); bad += 1
    if not re.match(r"^[0-9a-f]{40}$", e.get("uid","")): print("BAD-UID", e.get("uid")); bad += 1
    for tf in ("start_utc","finish_utc","discovered_at","last_seen_at"):
        v = e.get(tf)
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", v): print("BAD-TIME", tf, v, e.get("uid")); bad += 1
    u = e.get("uid")
    if u in uids: print("DUP-UID", u); bad += 1
    uids.add(u)
print("VIOLATIONS:", bad)
# window check today-1 .. +60
from datetime import datetime, timezone, timedelta
now = datetime.now(timezone.utc)
lo = (now - timedelta(days=1)).date().isoformat(); hi = (now + timedelta(days=60)).date().isoformat()
out = [e["uid"] for e in d if not (lo <= e["start_utc"][:10] <= hi)]
print("OUT-OF-WINDOW:", len(out), out[:5])
# wellness delta: which wellness events are new from now_bali?
print("WELLNESS:", [(e["name"][:50], e["source"]) for e in d if e.get("category")=="Wellness"])
print("NOWBALI:", [(e["name"][:55], e.get("category"), e["start_utc"][:10]) for e in d if e.get("source")=="now_bali"])
# ICS checks
ics = open(r"C:\code\lewagon-calendar\data\bali-events.ics", "rb").read()
print("ICS bytes:", len(ics))
print("has-LF-only:", bool(re.search(rb"(?<!\r)\n", ics)))
print("has-CRCR:", b"\r\r\n" in ics)
print("VEVENT:", ics.count(b"BEGIN:VEVENT"))
lr = json.load(open(r"C:\code\lewagon-calendar\data\last_run.json", encoding="utf-8"))
print("LASTRUN:", json.dumps(lr, indent=1)[:800])
