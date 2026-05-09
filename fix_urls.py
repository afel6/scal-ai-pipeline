import os

base = r'c:\Users\Asus\Downloads\scal-ai-pipeline\frontend\src'
for f in ['SidebarTabs.jsx', 'VisualAudit.jsx']:
    path = os.path.join(base, f)
    with open(path, 'r', encoding='utf-8') as fh:
        content = fh.read()
    new_content = content.replace("'http://localhost:8000'", "''")
    if new_content != content:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(new_content)
        print(f'Fixed {f}')
    else:
        print(f'{f}: no change needed')
