import json, urllib.request

def txt(prop):
    # Notion rich-text: list of [text, annotations]; date cells use "\u2023" marker
    if not prop:
        return ''
    parts = []
    for seg in prop:
        if seg and seg[0] not in ('\u2023',):
            parts.append(seg[0])
    return ''.join(parts)

def dat(prop):
    if not prop:
        return ''
    for seg in prop:
        for ann in (seg[1] if len(seg) > 1 else []):
            if isinstance(ann, list) and ann and ann[0] == 'd':
                d = ann[1]
                return d.get('start_date', '') + (' -> ' + d.get('end_date', '') if d.get('end_date') else '')
    return txt(prop)

payload = {
  "collection": {"id": "1e969801-bbdf-80e7-8a2c-000b08442ada", "spaceId": "0fbdf48d-e926-47c1-968c-e574b09dad21"},
  "collectionView": {"id": "1e969801-bbdf-80fd-9479-e632cdf77811", "spaceId": "0fbdf48d-e926-47c1-968c-e574b09dad21"},
  "loader": {"userTimeZone": "Asia/Singapore", "sort": [],
             "reducers": {"calendar_results": {"type": "results", "filter": {"operator": "and", "filters": []}, "limit": 5000}}},
}
req = urllib.request.Request(
    'https://favolist.notion.site/api/v3/queryCollection',
    data=json.dumps(payload).encode(),
    headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'},
)
with urllib.request.urlopen(req, timeout=30) as r:
    data = json.loads(r.read().decode())
recmap = data['recordMap']['block']
res = data['result']['reducerResults']['calendar_results']
print('TOTAL rows:', len(res.get('blockIds') or []), '| recordMap pages:', sum(1 for v in recmap.values() if v.get('value', {}).get('value', {}).get('type') == 'page'))
n = 0
for bid in (res.get('blockIds') or [])[:12]:
    v = recmap.get(bid, {}).get('value', {}).get('value', {})
    p = v.get('properties', {})
    name = txt(p.get('title'))
    print(f"- {name[:55]:55s} | {dat(p.get('fja;')):24s} | {txt(p.get('hP[['))[:20]:20s} | {txt(p.get('~xjM'))[:45]}")
    n += 1
