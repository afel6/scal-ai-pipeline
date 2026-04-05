import zipfile, xml.etree.ElementTree as ET

path = r'c:\Users\Asus\Downloads\scal-ai-pipeline\PRC_Batch_Study_1774470802_SCAL_Final_Report.docx'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

def tag(name):
    return '{%s}%s' % (W, name)

with zipfile.ZipFile(path) as z:
    with z.open('word/document.xml') as f:
        root = ET.parse(f).getroot()

body = root.find('.//' + tag('body'))

# Extract everything as clean text
lines = []
for elem in body:
    local = elem.tag.split('}')[-1]
    if local == 'p':
        texts = [t.text for t in elem.iter(tag('t')) if t.text]
        text = ''.join(texts).strip()
        if text:
            lines.append(text)
    elif local == 'tbl':
        rows = elem.findall('.//' + tag('tr'))
        for r in rows:
            cells = []
            for c in r.findall(tag('tc')):
                cell_text = ' '.join(t.text for t in c.iter(tag('t')) if t.text).strip()
                cells.append(cell_text)
            lines.append('|' + '|'.join(cells) + '|')
        lines.append('')

print('\n'.join(lines))
