lines = [
    "| Sample No. | Depth (ft) | Horiz. Permeability (mD) | Porosity (%) | Porosity (frac.) |",
    "Normalized Porosity (Phi z) | RQI | FZI | Unit No. |",
    "|:---|:---|:---|:---|:---|:---|:---|:---|:---|",
    "| 30 | 15373.0 | 3.01 | 8.42 | 0.0842 | 0.091941 | 0.18774 |",
    "2.041951 | 1 |",
    "",
    "Next paragraph..."
]

table_lines = []
for line in lines:
    if line.startswith('|') and '|' in line[1:]:
        table_lines.append(line)
    elif table_lines and '|' in line and not line.startswith('#'):
        table_lines[-1] += " " + line
    else:
        if table_lines:
            print("RENDER TABLE WITH ROWS:")
            for r in table_lines:
                print("  ->", r)
            table_lines = []
        if line:
            print("TEXT:", line)
            
if table_lines:
    print("RENDER TABLE WITH ROWS:")
    for r in table_lines:
        print("  ->", r)
