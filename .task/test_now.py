import sys
sys.path.insert(0, r"C:\code\lewagon-calendar\updater")
sys.path.insert(0, r"C:\code\lewagon-calendar\updater\sources")
import now_bali
from normalize import normalize
evs = now_bali.fetch()
print("RAW:", len(evs))
for e in evs:
    print(" -", e["start"], "|", e.get("category"), "|", e["name"][:60], "|", e["location"][:40])
run = "2026-09-25T00:00:00Z"
ok, bad = 0, []
for e in evs:
    n = normalize(e, "now_bali", run)
    if n: ok += 1
    else: bad.append(e["name"])
print("NORMALIZED:", ok, "BAD:", bad)
