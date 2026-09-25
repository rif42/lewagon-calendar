import re
html = open('.logs/sheet-html.html', encoding='utf-8').read()
# Find the row payload around the youtube URL: event fields live in adjacent cells
idx = html.find('BkO7h2oF6p4')
print(html[max(0, idx-3000):idx+1500].replace('\\u003d', '=').replace('\\n', '\n')[:4500])
