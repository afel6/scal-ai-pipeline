import sys
sys.path.append(r"C:\Users\Asus\Downloads\scal-ai-pipeline")
from scal_file_handler import SCALFileHandler
import json

handler = SCALFileHandler(r"C:\Users\Asus\Downloads\T1-31\T1-31\O-W Centrifuge Capillary Pressure, Drainge Cycle.xls")
res = handler.process()
print("Data type:", res['data_type'])
print("Extracted row count:", res['row_count'])
print("JSON:", json.dumps(res['extracted'], indent=2))
