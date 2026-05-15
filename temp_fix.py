import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = re.sub(r'âš\xa0ï¸? Gemini is currently under high demand', '⚠️ Gemini is currently under high demand', content)
content = re.sub(r'All keys exhausted on 503 â€” yield', 'All keys exhausted on 503 — yield', content)
content = re.sub(r'PRC Node Rotating â€” retrying', 'PRC Node Rotating — retrying', content)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
