headers_str = '| Sw | Ro at t | Rt | RI | n (pointwise) | log(Sw) (X) | log(RI) (Y) |'
sep_str = '| :------- | :----- | :------ | :------ | :------------ | :---------- | :---------- |'
row_str = '| 1.000000 | 1.6830 | 1.683000 | 1.000000 | NaN | 0.000000 | 0.000000 |'

# Mimic Claude's output breaking it into a list of strings
paragraphs = [
    headers_str,
    sep_str,
    "",
    row_str
]

sec = {'paragraphs': paragraphs}
content = {'sections': [sec], 'tables': []}

new_paragraphs = []
table_buffer = []

def process_table_buffer():
    if len(table_buffer) >= 3:
        headers = [c.strip() for c in table_buffer[0].split('|') if c.strip()]
        rows = []
        for row in table_buffer[2:]: # skip separator
            cols = [c.strip() for c in row.split('|') if c.strip()]
            if cols: rows.append(cols)
        if headers and rows:
            content['tables'].append({
                'caption': 'Data Table (Auto-Recovered)',
                'headers': headers,
                'rows': rows
            })
            table_buffer.clear()
            return
    new_paragraphs.extend(table_buffer)
    table_buffer.clear()

for para in sec.get('paragraphs', []):
    p_str = str(para).strip()
    
    if '\n' in p_str and '|' in p_str and ('---' in p_str or ':-' in p_str):
        lines = [l.strip() for l in p_str.split('\n')]
        table_buffer.extend([l for l in lines if l.count('|') >= 2])
        process_table_buffer()
        continue
        
    if p_str.count('|') >= 2:
        table_buffer.append(p_str)
    elif p_str == '':
        if not table_buffer:
            new_paragraphs.append(para)
        continue
    else:
        if table_buffer:
            process_table_buffer()
        new_paragraphs.append(para)

if table_buffer:
    process_table_buffer()
    
sec['paragraphs'] = new_paragraphs

import json
print(json.dumps(content, indent=2))
