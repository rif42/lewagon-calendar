"""Inspect honeycombers fetch output (ascii-safe)."""
import sys
sys.path.insert(0, "C:/code/lewagon-calendar/updater/sources")
import honeycombers
from collections import Counter

events = honeycombers.fetch()
lines = ["TOTAL: %d" % len(events)]
lines.append("CATS: %s" % dict(Counter(e.get("category") for e in events)))
for e in events:
    lines.append("%s | %s | %s | %s | %s" % (
        e["start"], e["category"], e["name"].encode("ascii", "replace").decode(),
        (e["location"] or "").encode("ascii", "replace").decode()[:70], e["source_url"]))
open("C:/code/lewagon-calendar/.logs/hc-smoke.txt", "w", encoding="utf-8").write("\n".join(lines))
print("wrote hc-smoke.txt with", len(lines), "lines")
print("CATS:", Counter(e.get("category") for e in events))
