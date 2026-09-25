"""Smoke-test honeycombers parser live."""
import sys
sys.path.insert(0, "C:/code/lewagon-calendar/updater")
sys.path.insert(0, "C:/code/lewagon-calendar/updater/sources")
import honeycombers
from collections import Counter

events = honeycombers.fetch()
print("TOTAL:", len(events))
print("CATS:", Counter(e.get("category") for e in events))
for e in events[:40]:
    print("-", e["start"], "|", e["category"], "|", e["name"][:70], "|", e["location"][:60])
open("C:/code/lewagon-calendar/.logs/hc-smoke.txt", "w", encoding="utf-8").write(
    "\n".join("%s | %s | %s | %s" % (e["start"], e["category"], e["name"], e["source_url"]) for e in events)
)
print("wrote .logs/hc-smoke.txt")
