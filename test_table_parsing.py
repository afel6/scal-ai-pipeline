import docx
import os

fname = r'C:\Users\Asus\Downloads\T1-31\T1-31\Draft Final Report (CCA&SCAL) Well # T1-31 (LV.2).docx'

try:
    doc = docx.Document(fname)
    for idx, child in enumerate(doc.element.body):
        if child.tag.endswith('p'):
            para = docx.text.paragraph.Paragraph(child, doc)
            text = para.text.strip()
            if '2.1.2' in text:
                print(f"Para {idx}: {text}")
        elif child.tag.endswith('tbl'):
            tbl = docx.table.Table(child, doc)
            tbl_text = ''
            for row in tbl.rows:
                for cell in row.cells:
                    tbl_text += cell.text + ' '
            if '2.1.2' in tbl_text:
                print(f"Table at {idx} contains 2.1.2")
except Exception as e:
    print(f"Error: {e}")
