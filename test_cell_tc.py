import docx

fname = r'C:\Users\Asus\Downloads\T1-31\T1-31\Draft Final Report (CCA&SCAL) Well # T1-31 (LV.2).docx'
doc = docx.Document(fname)
tbl = doc.tables[5] # just pick a table

seen_tc = []
for row in tbl.rows:
    for cell in row.cells:
        if cell._tc in seen_tc:
            print("Merged cell found!")
        else:
            seen_tc.append(cell._tc)
            print("New cell:", cell.text.strip()[:20])
