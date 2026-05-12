# -*- coding: utf-8 -*-
import sys
import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(r'PROTOCOL:\n  *', 'PROTOCOL:\n  •')
content = content.replace(r'\n  *', '\n  •')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
