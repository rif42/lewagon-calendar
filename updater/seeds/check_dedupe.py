import re, sys
sys.path.insert(0, r'C:\life\tmp\ig-verify\repo\scripts\instagram')
from merge import extract_existing_keys, norm
body = open(r'C:\code\lewagon-digitalbrain\notes\knowledge_bank\Bali Events List.md', encoding='utf-8').read()
keys = extract_existing_keys(body)
print('existing dated keys found:', len(keys))
for k in sorted(keys)[:8]:
    print(' -', k)
# overview table check
m = re.search(r'## Overview', body)
print('has Overview section:', bool(m))
m2 = re.search(r'\|---', body)
print('has markdown table:', bool(m2))
shorts = set(re.findall(r'IG:([A-Z0-9_]+)', body))
print('existing IG shortcodes:', shorts if shorts else '(none yet — merge never ran on real file)')
