from scal_file_handler import SCALFileHandler
import pandas as pd
df = pd.DataFrame({'Speed (RPM)': [1000, 2000, 3000], 'Produced Volume (cc)': [0.5, 1.2, 1.8]})
df.to_excel('test_centrifuge.xlsx', index=False, header=False)
h = SCALFileHandler('test_centrifuge.xlsx')
print(h.process())
