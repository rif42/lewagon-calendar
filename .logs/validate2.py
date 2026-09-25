"""Validate events.json vs schema + ICS regeneration check (ascii-safe)."""
import io, json, re
from collections import Counter

d = json.load(io.open("data/events.json", encoding="utf-8"))
s = json.load(io.open("events.schema.json", encoding="utf-8"))
print("total", len(d))
print("by_cat", dict(Counter(e.get("category") for e in d)))
print("by_src", dict(Counter(e.get("source") for e in d)))
print("by_area", dict(Counter(e.get("area") for e in d)))

req = s["required"]
props = s["properties"]
errs = []
uids = set()
for i, e in enumerate(d):
    for f in req:
        if f not in e:
            errs.append("%d missing %s" % (i, f))
    for k in e:
        if k not in props:
            errs.append("%d extra %s" % (i, k))
    if not re.match(r"^[0-9a-f]{40}$", e.get("uid", "")):
        errs.append("%d bad uid %r" % (i, e.get("uid")))
    if e.get("uid") in uids:
        errs.append("%d dup uid %s" % (i, e.get("uid")))
    uids.add(e.get("uid"))
    for f in ("area", "category", "status"):
        enum = props[f].get("enum")
        if enum and e.get(f) not in enum:
            errs.append("%d bad %s %r" % (i, f, e.get(f)))
    for f in ("start_utc", "finish_utc"):
        v = e.get(f)
        if v is not None and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", str(v)):
            errs.append("%d bad %s %r" % (i, f, v))
    if not isinstance(e.get("free"), bool):
        errs.append("%d bad free %r" % (i, e.get("free")))
print("SCHEMA ERRORS:", len(errs))
for x in errs[:20]:
    print("  ", x)

# window check: yesterday -> +60d, overlap semantics (finish >= lo, start <= hi)
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
lo = (now - timedelta(days=1)).date().isoformat()
hi = (now + timedelta(days=60)).date().isoformat()
out = [e for e in d
       if (e.get("finish_utc") or e.get("start_utc"), "")[0][:10] < lo
       or e.get("start_utc", "")[:10] > hi]
print("OUT-OF-WINDOW:", len(out))
for e in out[:10]:
    print("  ", e.get("start_utc"), e.get("name", "")[:60])

# discovery window focus: today -> +14d, non-nightlife
t0 = now.date().isoformat()
t1 = (now + timedelta(days=14)).date().isoformat()
win = [e for e in d if t0 <= e.get("start_utc", "")[:10] <= t1]
print("IN 14D WINDOW:", len(win), dict(Counter(e.get("category") for e in win)))

# ICS check
ics = io.open("data/bali-events.ics", encoding="utf-8", newline="").read()
vevents = ics.count("BEGIN:VEVENT")
print("ICS VEVENTs:", vevents, "vs json:", len(d))
print("ICS CRLF ok:", "\r\n" in ics, "| bare-LF lines:", sum(1 for l in ics.split("\r\n") if "\n" in l))
print("ICS has UID+DTSTAMP:", ics.count("UID:"), ics.count("DTSTAMP:"))
m = re.search(r"ran_at|DTSTAMP:(\d+T\d+Z)", ics)
print("ICS DTSTAMP sample:", m.group(1) if m else None)
