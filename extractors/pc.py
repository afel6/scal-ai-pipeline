import re
import pandas as pd
from extractors.base import BaseExtractor

class PCExtractor(BaseExtractor):
    """
    Extractor class for Porous Plate / Centrifuge Capillary Pressure (PC) datasets.
    """
    def extract(self) -> dict:
        """
        Two extraction paths: Priority (imbibition output table) and Fallback (standard Pc/Centrifuge RPM).
        """
        results = {}
        for sheet, df in self.raw_data.items():

            # ── PRIORITY: imbibition output table (signed Pc) ────────────────
            imb_found = False
            for i in range(len(df) - 3):
                row_vals = df.iloc[i].tolist()
                non_null = {str(v).lower().strip()
                            for v in row_vals
                            if pd.notna(v) and str(v).strip() != ''}
                if 'capillary' not in non_null or 'liquid' not in non_null:
                    continue
                if len(non_null) > 3:
                    continue
                next_non_null = {str(v).lower().strip()
                                 for v in df.iloc[i + 1].tolist()
                                 if pd.notna(v) and str(v).strip() != ''}
                if 'pressure' not in next_non_null or 'saturation' not in next_non_null:
                    continue

                cap_col = next(
                    (j for j, v in enumerate(row_vals)
                     if str(v).lower().strip() == 'capillary'), None
                )
                liq_col = next(
                    (j for j, v in enumerate(row_vals)
                     if str(v).lower().strip() == 'liquid'), None
                )
                if cap_col is None or liq_col is None:
                    continue

                data = df.iloc[i + 3:].reset_index(drop=True)
                pc_vals, sat_vals = [], []
                for _, r in data.iterrows():
                    pc  = pd.to_numeric(r[cap_col], errors='coerce')
                    sat = pd.to_numeric(r[liq_col], errors='coerce')
                    if not pd.isna(pc) and not pd.isna(sat):
                        pc_vals.append(float(pc))
                        sat_vals.append(float(sat))

                if not pc_vals:
                    continue

                sor_lab, sor_tc = None, None
                for i_s in range(len(df)):
                    row_s = df.iloc[i_s].tolist()
                    for j_s, cell in enumerate(row_s):
                        if not isinstance(cell, str):
                            continue
                        cell_l = cell.lower().strip()
                        if sor_lab is None and 'sor lab' in cell_l:
                            for k in range(j_s + 1, min(j_s + 4, len(row_s))):
                                v = pd.to_numeric(row_s[k], errors='coerce')
                                if not pd.isna(v):
                                    fv = float(v)
                                    sor_lab = round(fv * 100 if fv < 1.1 else fv, 4)
                                    break
                        elif sor_tc is None and re.search(r'sor\s+t\.?\s*c\.', cell_l):
                            for k in range(j_s + 1, min(j_s + 4, len(row_s))):
                                v = pd.to_numeric(row_s[k], errors='coerce')
                                if not pd.isna(v):
                                    fv = float(v)
                                    sor_tc = round(fv * 100 if fv < 1.1 else fv, 4)
                                    break

                results[sheet] = {
                    'Liquid_Sat_pct': sat_vals,
                    'Pc_psi':         pc_vals,
                    'cycle':          'imbibition',
                    'Sor_Lab_pct':    sor_lab,
                    'Sor_TC_pct':     sor_tc,
                }
                imb_found = True
                break

            if imb_found:
                continue

            # ── FALLBACK: standard Pc table or raw centrifuge data ───────────
            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]

                is_standard_pc = (
                    any(kw in c for c in row for kw in ['sw', 'sat', 'saturation']) and
                    any(kw in c for c in row for kw in ['pc', 'capillary', 'psia', 'mpa', 'press', 'pressure'])
                )
                is_centrifuge = (
                    any(kw in c for c in row for kw in ['rpm', 'speed', 'g-force', 'step']) and
                    any(kw in c for c in row for kw in ['volume', 'produced', 'cc', 'ml', 'production', 'recovery', 'fluid'])
                )

                if not (is_standard_pc or is_centrifuge):
                    continue

                headers = list(df.iloc[i])
                data = df.iloc[i + 1:].reset_index(drop=True)
                data.columns = range(len(data.columns))

                if is_standard_pc:
                    x_col = next((j for j, h in enumerate(headers) if any(kw in str(h).lower() for kw in ['sw', 'sat', 'saturation'])), None)
                    y_col = next((j for j, h in enumerate(headers) if any(kw in str(h).lower() for kw in ['pc', 'capillary', 'psia', 'mpa', 'press', 'pressure'])), None)
                    x_name, y_name = 'Sw', 'Pc'
                else:
                    x_col = next((j for j, h in enumerate(headers) if any(kw in str(h).lower() for kw in ['rpm', 'speed', 'g-force', 'step'])), None)
                    y_col = next((j for j, h in enumerate(headers) if any(kw in str(h).lower() for kw in ['volume', 'produced', 'cc', 'ml', 'production', 'recovery', 'fluid'])), None)
                    x_name, y_name = 'RPM', 'Produced Volume'

                if x_col is None or y_col is None or x_col == y_col:
                    continue

                x_vals, y_vals = [], []
                for idx, r in data.iterrows():
                    x = pd.to_numeric(r[x_col], errors='coerce')
                    y = pd.to_numeric(r[y_col], errors='coerce')
                    if not pd.isna(x) and not pd.isna(y):
                        x_vals.append(x)
                        y_vals.append(y)
                if x_vals:
                    results[sheet] = {x_name: x_vals, y_name: y_vals}
                    break

        self.extracted = {'type': 'PC', 'samples': results}
        return self.extracted
