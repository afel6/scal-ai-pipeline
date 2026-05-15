import sys
import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace import
content = re.sub(r'from scal_file_handler import SCALFileHandler', r'from scal_file_handler import SCALFileHandler, extract_file_data', content)

# Replace usage
old_usage = '''                    handler = SCALFileHandler(tmp_path)
                    result = handler.process()'''
new_usage = '''                    result = extract_file_data(tmp_path)'''
content = content.replace(old_usage, new_usage)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Updated app.py to use extract_file_data')
