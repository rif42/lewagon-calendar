"""Notion favolist source (Tier-1, public pages only, no auth).

Reuses the query logic from updater/seeds/notion_query.py:
unfiltered queryCollection against favolist.notion.site, date filtering
is done locally by the normalizer/merger, not by the Notion query.
"""

import sys

try:
    import requests
except ImportError:  # pragma: no cover - fallback for bare envs
    requests = None  # type: ignore[assignment]

SOURCE = "notion_favolist"
TIER = 1

_BASE_URL = "https://favolist.notion.site"
_QUERY_URL = _BASE_URL + "/api/v3/queryCollection"
_UA = "lewagon-event-calendar/1.0 (+https://github.com/lewagon-event-calendar)"
_TIMEOUT = 20

_PAYLOAD = {
    "collection": {
        "id": "1e969801-bbdf-80e7-8a2c-000b08442ada",
        "spaceId": "0fbdf48d-e926-47c1-968c-e574b09dad21",
    },
    "collectionView": {
        "id": "1e969801-bbdf-80fd-9479-e632cdf77811",
        "spaceId": "0fbdf48d-e926-47c1-968c-e574b09dad21",
    },
    "loader": {
        "userTimeZone": "Asia/Singapore",
        "sort": [],
        "reducers": {
            "calendar_results": {
                "type": "results",
                "filter": {"operator": "and", "filters": []},
                "limit": 5000,
            }
        },
    },
}


def _txt(prop):
    """Notion rich-text: list of [text, annotations]; date cells use U+2023 marker."""
    if not prop:
        return ""
    parts = []
    for seg in prop:
        if seg and seg[0] not in ("\u2023",):
            parts.append(seg[0])
    return "".join(parts)


def _dat(prop):
    if not prop:
        return ""
    for seg in prop:
        for ann in seg[1] if len(seg) > 1 else []:
            if isinstance(ann, list) and ann and ann[0] == "d":
                d = ann[1]
                return d.get("start_date", "") + (
                    " -> " + d.get("end_date", "") if d.get("end_date") else ""
                )
    return _txt(prop)


def _split_range(raw):
    raw = (raw or "").strip()
    if not raw:
        return "", ""
    if " -> " in raw:
        start, finish = raw.split(" -> ", 1)
        return start.strip(), finish.strip()
    return raw, ""


def _pick_url(*candidates):
    for cand in candidates:
        cand = (cand or "").strip()
        if cand.startswith("http://") or cand.startswith("https://"):
            return cand
    return _BASE_URL + "/"


def _map_row(props):
    name = _txt(props.get("title"))
    date_raw = _dat(props.get("fja;"))
    start, finish = _split_range(date_raw)
    type_text = _txt(props.get("hP[["))
    loc_url = _txt(props.get("~xjM"))
    event_url = _txt(props.get("PMXu"))
    cost = _txt(props.get("fWMC"))
    source_url = _pick_url(event_url, loc_url)
    description = "type: %s" % type_text if type_text else ""
    lowered = cost.lower()
    free = bool(lowered) and "free" in lowered
    return {
        "name": name,
        "title": name,
        "start": start,
        "finish": finish,
        "location": loc_url,
        "description": description,
        "area": "",
        "category": type_text,
        "cost": cost,
        "free": free,
        "source_url": source_url,
        "status": "confirmed",
    }


def _query_collection():
    headers = {
        "Content-Type": "application/json",
        "User-Agent": _UA,
    }
    if requests is not None:
        resp = requests.post(
            _QUERY_URL, json=_PAYLOAD, headers=headers, timeout=_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()
    import json as _json
    import urllib.request as _urllib

    req = _urllib.Request(
        _QUERY_URL,
        data=_json.dumps(_PAYLOAD).encode(),
        headers=headers,
    )
    with _urllib.urlopen(req, timeout=_TIMEOUT) as r:
        return _json.loads(r.read().decode())


def fetch():
    """Fetch raw favolist events. Never raises: on failure logs to stderr, returns []."""
    try:
        data = _query_collection()
        record_map = data.get("recordMap", {}).get("block", {})
        result = data.get("result", {}).get("reducerResults", {}).get(
            "calendar_results", {}
        )
        block_ids = result.get("blockIds") or []
        events = []
        for bid in block_ids:
            try:
                value = record_map.get(bid, {}).get("value", {}).get("value", {})
                props = value.get("properties", {})
                row = _map_row(props)
                if not row["name"] and not row["start"]:
                    continue
                events.append(row)
            except Exception as exc:  # skip bad rows, keep the run alive
                print(
                    "[%s] skipping bad row %s: %r" % (SOURCE, bid, exc),
                    file=sys.stderr,
                )
                continue
        return events
    except Exception as exc:
        print("[%s] fetch failed: %r" % (SOURCE, exc), file=sys.stderr)
        return []
