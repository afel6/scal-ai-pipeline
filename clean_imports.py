import sys

with open('scal_file_handler.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

seen = set()
new_lines = []
for line in lines:
    stripped = line.strip()
    if stripped.startswith('import ') or stripped.startswith('from '):
        if stripped in seen:
            continue
        seen.add(stripped)
    new_lines.append(line)

with open('scal_file_handler.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Cleaned up duplicate imports')
