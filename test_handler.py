from scal_file_handler import robust_extract_scal
import json
r = robust_extract_scal(r'C:\Users\Asus\Downloads\FFCAL-OBP, T1-31.xls')
print('Engine:', r['engine_used'])
print('Sheets parsed:', len(r['sheets']))
print('Sheets with data:', sum(1 for s in r['sheets'] if s['data_block']))
for s in r['sheets'][:3]:
    if s['data_block']:
        print(f'  {s["name"]}: track={s["track"]}, n_rows={s["data_block"]["n_rows"]}, well={s["metadata"].get("well")}')
print('Errors:', r['errors'])
