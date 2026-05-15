import sys, re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_section = """
## PHASE 4.2: SINGLE-RESPONSE ECONOMY (NO DUPLICATE PLOTS)
For multi-pressure, multi-sample, or multi-condition datasets, you may call the fitting tools as many times as needed internally to gather values — but emit only ONE plot payload (__PRC_PLOT__) per response. Choose the most informative single plot:
- For FF-vs-OBP datasets: ONE composite plot showing all data points across all pressures, with the composite fit line.
- For RI datasets with multiple samples: ONE log-log plot with all samples overlaid.
- For MICP with multiple samples: ONE semi-log Pc plot with sample curves.

Do NOT emit a separate plot per pressure step, per sample, or per intermediate tool call. Do NOT show intermediate "DATA CERTIFIED" banners between tool calls. Run all your analysis internally first, then produce ONE clean structured response with ONE plot and ONE Section 5 audit at the end.

One response = one analysis cycle = one plot + one Executive Summary + one Section 5.

# PHASE 5: UI SPECIFICATIONS"""

content = re.sub(r'# PHASE 5: UI SPECIFICATIONS', new_section.strip(), content)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS")
