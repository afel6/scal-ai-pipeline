import sys

with open('scal_file_handler.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Add missing imports if not present
new_lines = []
added_re = False
added_pathlib = False

for line in lines:
    if 'import pandas' in line and not added_re:
        new_lines.append('import re\n')
        new_lines.append('from pathlib import Path\n')
        added_re = True
    new_lines.append(line)

with open('scal_file_handler.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Updated imports in scal_file_handler.py')
