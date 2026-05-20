from file_reader import read_file
import json

fname = r'C:\Users\Asus\Downloads\T1-31\T1-31\Draft Final Report (CCA&SCAL) Well # T1-31 (LV.2).docx'
res = read_file(fname, target_identifier="Table 2.1.1")
if "error" in res:
    print("Error:", res["error"])
else:
    print(res["content"][:2000])
