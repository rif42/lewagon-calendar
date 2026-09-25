"""Check emitted finish_utc for the 4 promos + state."""
import io, json
d = json.load(io.open("data/events.json", encoding="utf-8"))
for e in d:
    if (e.get("source_url") or "") in (
        "https://thehoneycombers.com/bali/event/atomic-17/",
        "https://thehoneycombers.com/bali/event/cascayu-promotion/",
        "https://thehoneycombers.com/bali/event/mooncake-for-the-mid-autumn-festival/",
        "https://thehoneycombers.com/bali/event/blue-peaceful-frequency-a-collective-art-exhibition/",
    ):
        print(e["start_utc"], "->", e["finish_utc"], "|", e["name"][:50].encode("ascii", "replace").decode())
