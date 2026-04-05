import re

text = """| Sample No. | Depth (ft) | Horiz. Permeability (mD) | Porosity (%) | Porosity (frac.) |
Normalized Porosity (Phi z) | RQI | FZI | Unit No. |
|:---|:---|:---|:---|:---|:---|:---|:---|:---|
| 30 | 15373.0 | 3.01 | 8.42 | 0.0842 | 0.091941 | 0.18774 |
2.041951 | 1 |"""

lines = text.split('\n')
table_lines = []

for line in lines:
    line = line.strip()
    print(f"[{line.startswith('|')}] [{line.endswith('|')}] {line}")
