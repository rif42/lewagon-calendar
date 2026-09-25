"""Smoke-test balisquad parser live (ascii-safe)."""
import sys
sys.path.insert(0, "C:/code/lewagon-calendar/updater/sources")
import balisquad
from collections import Counter

events = balisquad.fetch()
lines = ["TOTAL: %d" % len(events)]
lines.append("CATS: %s" % dict(Counter(e.get("category") for e in events)))
for e in events:
    lines.append("%s | %s | %s | %s | %s" % (
        e["start"], e["category"], e["name"].encode("ascii", "replace").decode(),
        (e["location"] or "").encode("ascii", "replace").decode()[:70], e["source_url"]))
open("C:/code/lewagon-calendar/.logs/bs-smoke.txt", "w", encoding="utf-8").write("\n".join(lines))
print("CATS:", Counter(e.get("category") for e in events))
print("TOTAL:", len(events))
