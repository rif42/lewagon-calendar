"""Validate pipeline outputs per task step 1. Writes report to .logs/validate.json."""
import json, re, sys
from datetime import datetime, timezone
ROOT = __import__('pathlib').Path(r'C:\code\lewagon-calendar')
errors, checks = [], {}

# --- last_run per-source status + parser assert ---
last_run = json.loads((ROOT/'data/last_run.json').read_text(encoding='utf-8'))
checks['ran_at'] = last_run.get('ran_at')
for name, st in (last_run.get('sources') or {}).items():
    dated = st.get('normalized', 0)
    ok = st.get('status') == 'ok' and dated >= 1
    checks[f'parser_assert.{name}'] = {'status': st.get('status'), 'raw': st.get('count'), 'normalized': dated, 'pass': ok}
    if not ok:
        errors.append(f"parser assert failed for source {name}: {st}")

# --- events.json vs schema ---
schema = json.loads((ROOT/'events.schema.json').read_text(encoding='utf-8'))
events = json.loads((ROOT/'data/events.json').read_text(encoding='utf-8'))
checks['event_count'] = len(events)
assert isinstance(events, list), 'events.json must be a list'
req = schema['required']
props = schema['properties']
uid_re = re.compile(r'^[0-9a-f]{40}$')
dt_re = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
import hashlib, unicodedata
def norm_title(t):
    t = unicodedata.normalize('NFKC', str(t or ''))
    return re.sub(r'\s+', ' ', t).strip().casefold()
recurring_re = re.compile(r'\bevery\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', re.I)
for i, e in enumerate(events):
    for f in req:
        if f not in e or e[f] in (None, ''):
            errors.append(f'event[{i}] missing required {f}: {e.get("name")}')
    if not uid_re.match(str(e.get('uid',''))):
        errors.append(f'event[{i}] bad uid: {e.get("uid")}')
    else:
        expect = hashlib.sha1(f"{e.get('source','').strip()}|{norm_title(e.get('name'))}|{str(e.get('start_utc','')).strip()}".encode()).hexdigest()
        if expect != e['uid']:
            errors.append(f"event[{i}] uid mismatch recompute: {e.get('name')} got {e['uid']} want {expect}")
    if not dt_re.match(str(e.get('start_utc',''))):
        errors.append(f"event[{i}] bad start_utc: {e.get('start_utc')}")
    fu = e.get('finish_utc')
    if fu is not None and not dt_re.match(str(fu)):
        errors.append(f"event[{i}] bad finish_utc: {fu}")
    if e.get('area') not in props['area']['enum']:
        errors.append(f"event[{i}] bad area: {e.get('area')}")
    if e.get('category') not in props['category']['enum']:
        errors.append(f"event[{i}] bad category: {e.get('category')}")
    if e.get('status') not in props['status']['enum']:
        errors.append(f"event[{i}] bad status: {e.get('status')}")
    blob = f"{e.get('name','')} {e.get('description','')}"
    if recurring_re.search(blob) and not dt_re.match(str(e.get('start_utc',''))):
        errors.append(f"event[{i}] bare recurring without dated instance: {e.get('name')}")
    if recurring_re.search(str(e.get('name',''))):
        # name itself contains 'every Saturday' style -> bare series, violation
        errors.append(f"event[{i}] recurring bare name: {e.get('name')}")
checks['schema_violations'] = len([x for x in errors if 'event[' in x])

# --- ICS regenerated same run from same merged list ---
ics_raw = (ROOT/'data/bali-events.ics').read_bytes()
checks['ics_crlf'] = b'\r\n' in ics_raw and ics_raw.replace(b'\r\n', b'').count(b'\n') == 0 and b'\r\r\n' not in ics_raw
if not checks['ics_crlf']:
    errors.append('ICS line endings are not clean single-CRLF')
ics = ics_raw.decode('utf-8')
uids_ics = re.findall(r'UID:([0-9a-f]{40})@lewagon-calendar', ics)
uids_json = [e['uid'] for e in events]
checks['ics_vevent_count'] = ics.count('BEGIN:VEVENT')
checks['ics_uid_match_json'] = sorted(uids_ics) == sorted(uids_json)
if sorted(uids_ics) != sorted(uids_json):
    errors.append(f"ICS/JSON uid mismatch: ics={len(uids_ics)} json={len(uids_json)} only_ics={sorted(set(uids_ics)-set(uids_json))[:3]} only_json={sorted(set(uids_json)-set(uids_ics))[:3]}")
m = re.search(r'DTSTAMP:(\d{8}T\d{6}Z)', ics)
checks['ics_dtstamp'] = m.group(1) if m else None
ran = last_run.get('ran_at','')
try:
    rdt = datetime.fromisoformat(ran.replace('Z','+00:00')).astimezone(timezone.utc)
    checks['ics_dtstamp_matches_run'] = (m and m.group(1) == rdt.strftime('%Y%m%dT%H%M%SZ'))
    if not checks['ics_dtstamp_matches_run']:
        errors.append(f"ICS DTSTAMP {m.group(1) if m else None} != last_run {ran}")
except Exception as ex:
    errors.append(f'ran_at parse fail: {ex}')
checks['event_count_matches_last_run'] = (last_run.get('event_count') == len(events))
if not checks['event_count_matches_last_run']:
    errors.append('last_run.event_count != len(events.json)')
# window check: discovery window today..+14d vs prune 60d (prune untouched)
today = datetime.now(timezone.utc)
checks['window_note'] = 'prune rolling 60d untouched; discovery focus today..+14d for manual merges only'

out = {'checks': checks, 'errors': errors, 'pass': not errors}
(ROOT/'.logs/validate.json').write_text(json.dumps(out, indent=2), encoding='utf-8')
print(json.dumps(out, indent=2))
sys.exit(0 if not errors else 1)
