import re
body = open(r'C:\code\lewagon-digitalbrain\notes\knowledge_bank\Bali Events List.md', encoding='utf-8').read()
i = body.find('## Overview')
out = open(r'C:\life\tmp\ig-verify\overview_snippet.txt', 'w', encoding='utf-8')
out.write(body[i:i+1500])
out.close()
print('written')
secs = re.findall(r'^## \d+\)\s*(.+)$', body, re.M)
print('numbered sections:', len(secs))
for s in secs[:5]:
    print(' -', s[:70])
starts = re.findall(r'- \*\*Start:\*\* ([0-9-]+)', body)
print('Start fields:', len(starts), starts[:5])
