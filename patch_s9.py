import re
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

s9 = '\nSECTION 9 — VISION PROTOCOL:\n- Analyze lab photos for configuration errors (valves, core seating).\n- Ensure visual evidence matches the reported digital SCAL data.\n'

if 'SECTION 9 — VISION PROTOCOL' not in content:
    content = re.sub(r'(\n)(\"\"\")', r'\1' + s9 + r'\1\2', content, count=1)
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Patched app.py with Section 9')
else:
    print('SECTION 9 already present')
