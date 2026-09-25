import json
d = json.load(open(r"C:\code\lewagon-calendar\data\events.json", encoding="utf-8"))
byuid = {e["uid"]: e for e in d}
for u in ['5f797cf84a20d65af2a666f63c863b2ec7c5ae16', '24bcad02d94db5a803ad2c6ed9f0dc9b35a801b3', '6de3b0c930e929c0c27ba2b8f56408614c2435e0', 'd813c53654d76fe0add18d1928ad98cfb61e0165', 'c89e33f2dada84596e1586ce442b500c9d9e18bf']:
    e = byuid.get(u)
    if e: print(u[:8], "|", e["start_utc"], "|", e["finish_utc"], "|", e["category"], "|", e["source"], "|", e["name"][:60])
    else: print(u[:8], "NOT IN JSON?!")
print("---- brunch search ----")
for e in d:
    if "brunch" in e["name"].lower() or "wellness" in e["name"].lower():
        print(e["start_utc"], "|", e["finish_utc"], "|", e["category"], "|", e["source"], "|", e["name"][:60])
print("---- notion in window? ----")
print("notion count:", sum(1 for e in d if e["source"]=="notion_favolist"))
