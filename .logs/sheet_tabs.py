import re
html = open('.logs/sheet-html.html', encoding='utf-8').read()
print('len', len(html))
for pat in [r'sheets?[^<]{0,80}', r'gid[^0-9]{0,5}\d+', r'Tally[^<]{0,120}', r'youtube[^<]{0,120}', r'BkO7h2oF6p4']:
    hits = re.findall(pat, html, re.I)[:8]
    print('PAT', pat, '->', len(hits))
    for h in hits[:5]:
        print('   ', h[:160])
