"""Inspect the 4 out-of-window events."""
import io, json
d = json.load(io.open("data/events.json", encoding="utf-8"))
st = json.load(io.open("data/state.json", encoding="utf-8"))
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
lo = (now - timedelta(days=1)).date().isoformat()
for e in d:
    if e.get("start_utc", "")[:10] < lo:
        print(e.get("start_utc"), "|", e.get("source"), "|", e.get("name", "")[:60].encode("ascii", "replace").decode())
        print("   loc:", (e.get("location") or "").encode("ascii", "replace").decode()[:100])
        print("   url:", e.get("source_url"))
        print("   discovered:", e.get("discovered_at"), "last_seen:", e.get("last_seen_at"), "status:", e.get("status"))
print("state events:", len(st.get("events", {})))
