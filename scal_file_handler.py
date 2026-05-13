"""
SCAL AI - File Handler
======================
This is the exact logic used to read, identify, and extract
data from any SCAL file uploaded by an engineer.

Usage:
    handler = SCALFileHandler(file_path)
    result = handler.process()
    # result contains: data_type, dataframes, summary, raw_text
"""

import pandas as pd
import numpy as np
import json
import os


class SCALFileHandler:

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.extension = os.path.splitext(file_path)[1].lower()
        self.sheet_names = []
        self.raw_data = {}      # sheet_name -> DataFrame (raw, no header)
        self.data_type = None   # identified SCAL type
        self.extracted = {}     # cleaned, ready-to-plot data

    # ------------------------------------------------------------------ #
    # STEP 1 — READ THE FILE (extension-aware)
    # ------------------------------------------------------------------ #

    def read(self):
        """Read the file efficiently by scanning sheet names first."""

        if self.extension in ('.xlsx', '.xlsm', '.xls', '.ods'):
            engine = 'openpyxl' if self.extension in ('.xlsx', '.xlsm') else ('xlrd' if self.extension == '.xls' else 'odf')
            xl = pd.ExcelFile(self.file_path, engine=engine)
            self.sheet_names = xl.sheet_names
            
            # Optimization: Only read sheets that likely contain SCAL data
            # This prevents "taking too long" on huge multi-sheet workbooks.
            target_sheets = []
            all_keywords = []
            for klist in self.KEYWORDS.values():
                all_keywords.extend(klist)
            
            for sheet in self.sheet_names:
                s_lower = sheet.lower()
                # Direct match or likely candidate
                if any(kw in s_lower for kw in ['scal', 'core', 'data', 'test', 'result', 'analysis', 'summary', 'centrifuge', 'micp', 'permeability', 'porosity']):
                    target_sheets.append(sheet)
                elif any(kw in s_lower for kw in all_keywords):
                    target_sheets.append(sheet)
            
            # If no sheets match, we must read the first few just in case
            if not target_sheets and self.sheet_names:
                target_sheets = self.sheet_names[:3] 

            for sheet in target_sheets:
                self.raw_data[sheet] = pd.read_excel(
                    xl, sheet_name=sheet, header=None
                )
            
            # Update sheet_names to only reflect what we actually read
            self.sheet_names = list(self.raw_data.keys())

        elif self.extension == '.csv':
            df = pd.read_csv(self.file_path, header=None)
            self.sheet_names = ['Sheet1']
            self.raw_data['Sheet1'] = df

        else:
            raise ValueError(f"Unsupported file type: {self.extension}")

        return self

    # ------------------------------------------------------------------ #
    # STEP 2 — IDENTIFY DATA TYPE (keyword scan across all sheets)
    # ------------------------------------------------------------------ #

    KEYWORDS = {
        'MICP': [
            'mercury', 'hg', 'intrusion', 'psia', 'mpa', 'threshold pressure',
            'drainage', 'imbibition', 'cumulative intrusion',
            'capillary pressure', 'pore throat', 'washburn'
        ],
        'KR': [
            'kro', 'krw', 'krg', 'relative permeability',
            'end point', 'sor', 'swi', 'sgr', 'water flood', 'kr'
        ],
        'PC': [
            'porous plate', 'centrifuge', 'brine saturation',
            'oil-brine', 'air-brine', 'reservoir conditions',
            'rpm', 'speed', 'produced volume', 'cc', 'g-force'
        ],
        'FRF': [
            'formation factor', 'formation resistivity factor',
            'cementation', 'tortuosity', '100% brine', 'archie', 'rt', 'ro'
        ],
        'RI': [
            'resistivity index', 'saturation exponent',
            'partial saturation', 'rt', 'ro', ' ri '
        ],
        'WETTABILITY': [
            'amott', 'usbm', 'wettability index', 'iw', 'io',
            'spontaneous imbibition', 'water wet', 'oil wet'
        ],
        'NMR': [
            'nmr', 't2', 't2 distribution', 'relaxation', 'bvi',
            'ffi', 'free fluid', 'bulk volume irreducible', 't2 cutoff'
        ],
        'PVT': [
            'bo', 'rs', 'gor', 'bubble point', 'dew point',
            'bg', 'formation volume factor', 'differential liberation'
        ],
        'RCAL': [
            'routine core', 'air permeability', 'klinkenberg',
            'grain density', 'plug', 'horizontal perm', 'vertical perm'
        ],
    }

    def identify(self):
        """Scan all sheets for keywords to identify the SCAL data type."""
        scores = {k: 0 for k in self.KEYWORDS}

        for sheet, df in self.raw_data.items():
            # Flatten all cell values to one big lowercase string
            text = ' '.join(
                str(v).lower()
                for v in df.values.flatten()
                if pd.notna(v)
            )
            for data_type, keywords in self.KEYWORDS.items():
                for kw in keywords:
                    if kw in text:
                        scores[data_type] += 1

        best = max(scores, key=scores.get)
        if scores[best] == 0:
            self.data_type = 'UNKNOWN'
        else:
            self.data_type = best

        return self

    # ------------------------------------------------------------------ #
    # STEP 3 — EXTRACT DATA (type-specific parsers)
    # ------------------------------------------------------------------ #

    def extract(self):
        """Route to the correct extractor based on identified data type."""
        extractors = {
            'MICP':        self._extract_micp,
            'KR':          self._extract_kr,
            'FRF':         self._extract_frf,
            'RI':          self._extract_ri,
            'NMR':         self._extract_nmr,
            'PVT':         self._extract_pvt,
            'RCAL':        self._extract_rcal,
            'WETTABILITY': self._extract_wettability,
            'PC':          self._extract_pc,
        }
        if self.data_type in extractors:
            extractors[self.data_type]()
        return self

    # ---- MICP ---- #
    def _extract_micp(self):
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if not any(kw in text for kw in ['mercury', 'hg', 'psia', 'mpa', 'intrusion', 'capillary pressure']):
                continue
                
            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]
                if any(kw in c for c in row for kw in ['press', 'psia', 'mpa']) and any(kw in c for c in row for kw in ['sat', 'hg', 'pv', 'intrusion']):
                    headers = list(df.iloc[i])
                    data = df.iloc[i+1:].reset_index(drop=True)
                    data.columns = range(len(data.columns))
                    press_col = next((j for j, h in enumerate(headers) if any(kw in str(h).lower() for kw in ['press', 'psia', 'mpa'])), None)
                    sat_col = next((j for j, h in enumerate(headers) if any(kw in str(h).lower() for kw in ['sat', 'hg', 'pv', 'intrusion'])), None)
                    
                    if press_col is not None and sat_col is not None:
                        cycle_col = next((j for j, h in enumerate(headers) if 'cycle' in str(h).lower()), None)
                        
                        drainage = {'pressure': [], 'sat_pv': []}
                        imbibition = {'pressure': [], 'sat_pv': []}
                        
                        for idx, r in data.iterrows():
                            p = pd.to_numeric(r[press_col], errors='coerce')
                            s = pd.to_numeric(r[sat_col], errors='coerce')
                            if pd.isna(p) or pd.isna(s):
                                continue
                                
                            if s in (0.0, 1.0, 100.0, 30.0):
                                continue
                                
                            c = str(r[cycle_col]).strip().upper() if cycle_col is not None else 'D'
                            if c.startswith('I'):
                                imbibition['pressure'].append(round(float(p), 3))
                                imbibition['sat_pv'].append(round(float(s), 4))
                            else:
                                drainage['pressure'].append(round(float(p), 3))
                                drainage['sat_pv'].append(round(float(s), 4))
                                
                        if drainage['pressure'] or imbibition['pressure']:
                            results[sheet] = {
                                'drainage': drainage,
                                'imbibition': imbibition
                            }
                    break

        self.extracted = {'type': 'MICP', 'samples': results}

    # ---- RELATIVE PERMEABILITY ---- #
    def _extract_kr(self):
        """
        Look for columns: Sw (or Sg), Kro, Krw (or Krg)
        Works across any sheet that has these headers.
        """
        results = {}
        kr_keywords = {'sw', 'sg', 'kro', 'krw', 'krg', 'kr'}

        for sheet, df in self.raw_data.items():
            header_row = None
            for i in range(min(30, len(df))):
                row_text = [str(v).lower().strip() for v in df.iloc[i] if pd.notna(v)]
                matches = sum(1 for cell in row_text if any(kw in cell for kw in kr_keywords))
                if matches >= 2:
                    header_row = i
                    break

            if header_row is None:
                continue

            headers = [str(v).lower().strip() for v in df.iloc[header_row]]
            data_df = df.iloc[header_row + 1:].reset_index(drop=True)
            data_df.columns = range(len(headers))

            col_map = {}
            for j, col in enumerate(headers):
                if 'sw' in col:   col_map['Sw']  = j
                elif 'sg' in col:   col_map['Sg']  = j
                elif 'kro' in col:  col_map['Kro'] = j
                elif 'krw' in col:  col_map['Krw'] = j
                elif 'krg' in col:  col_map['Krg'] = j

            indep_var = 'Sw' if 'Sw' in col_map else ('Sg' if 'Sg' in col_map else None)
            extracted_cols = {k: [] for k in col_map.keys()}
            
            for idx, r in data_df.iterrows():
                if indep_var:
                    x = pd.to_numeric(r[col_map[indep_var]], errors='coerce')
                    if pd.isna(x):
                        continue
                
                has_dep = False
                for k, j in col_map.items():
                    if k != indep_var:
                        v = pd.to_numeric(r[j], errors='coerce')
                        if not pd.isna(v):
                            has_dep = True
                            
                if not has_dep and len(col_map) > 1:
                    continue
                    
                for k, j in col_map.items():
                    v = pd.to_numeric(r[j], errors='coerce')
                    extracted_cols[k].append(v if not pd.isna(v) else None)

            clean_extracted = {k: v for k, v in extracted_cols.items() if any(val is not None for val in v)}
            if clean_extracted:
                results[sheet] = clean_extracted

        self.extracted = {'type': 'KR', 'samples': results}

    # ---- FORMATION RESISTIVITY FACTOR ---- #
    def _extract_frf(self):
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if 'formation factor' not in text and 'frf' not in text and 'rt' not in text and 'ro' not in text and 'archie' not in text:
                continue
            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]
                if any('poros' in c for c in row) and any('factor' in c or ' f' == c or 'rt' in c or 'ro' in c for c in row):
                    headers = list(df.iloc[i])
                    data = df.iloc[i+1:].reset_index(drop=True)
                    data.columns = range(len(data.columns))
                    phi_col = next((j for j, h in enumerate(headers) if 'poros' in str(h).lower()), None)
                    f_col   = next((j for j, h in enumerate(headers) if 'factor' in str(h).lower() or str(h).strip().upper() == 'F' or 'rt' in str(h).lower() or 'ro' in str(h).lower()), None)
                    if phi_col is not None and f_col is not None:
                        phi_vals, f_vals = [], []
                        for idx, r in data.iterrows():
                            p = pd.to_numeric(r[phi_col], errors='coerce')
                            f = pd.to_numeric(r[f_col], errors='coerce')
                            if not pd.isna(p) and not pd.isna(f):
                                if p > 30 or p < 2:
                                    continue
                                phi_vals.append(p)
                                f_vals.append(f)
                        if phi_vals:
                            results[sheet] = {'porosity': phi_vals, 'F': f_vals}
                    break
        self.extracted = {'type': 'FRF', 'samples': results}

    # ---- RESISTIVITY INDEX ---- #
    def _extract_ri(self):
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if 'resistivity index' not in text and ' ri ' not in text and 'rt' not in text and 'ro' not in text:
                continue
            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]
                if any('sw' in c for c in row) and any('ri' in c or 'index' in c or 'rt' in c or 'ro' in c for c in row):
                    headers = list(df.iloc[i])
                    data = df.iloc[i+1:].reset_index(drop=True)
                    data.columns = range(len(data.columns))
                    sw_col = next((j for j, h in enumerate(headers) if 'sw' in str(h).lower()), None)
                    ri_col = next((j for j, h in enumerate(headers) if 'ri' in str(h).lower() or 'index' in str(h).lower() or 'rt' in str(h).lower() or 'ro' in str(h).lower()), None)
                    if sw_col is not None and ri_col is not None:
                        sw_vals, ri_vals = [], []
                        for idx, r in data.iterrows():
                            s = pd.to_numeric(r[sw_col], errors='coerce')
                            ri = pd.to_numeric(r[ri_col], errors='coerce')
                            if not pd.isna(s) and not pd.isna(ri):
                                if s in (0.0, 1.0, 100.0, 30.0):
                                    continue
                                sw_vals.append(s)
                                ri_vals.append(ri)
                        if sw_vals:
                            results[sheet] = {'Sw': sw_vals, 'RI': ri_vals}
                    break
        self.extracted = {'type': 'RI', 'samples': results}

    # ---- NMR ---- #
    def _extract_nmr(self):
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if 't2' not in text and 'nmr' not in text:
                continue
            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]
                if any('t2' in c for c in row):
                    headers = list(df.iloc[i])
                    data = df.iloc[i+1:].reset_index(drop=True)
                    data.columns = range(len(data.columns))
                    t2_col  = next((j for j, h in enumerate(headers) if 't2' in str(h).lower()), None)
                    amp_col = next((j for j, h in enumerate(headers) if any(k in str(h).lower() for k in ['amp', 'incr', 'pore', 'volume'])), None)
                    if t2_col is not None and amp_col is not None:
                        t2_vals, amp_vals = [], []
                        for idx, r in data.iterrows():
                            t = pd.to_numeric(r[t2_col], errors='coerce')
                            a = pd.to_numeric(r[amp_col], errors='coerce')
                            if not pd.isna(t) and not pd.isna(a):
                                t2_vals.append(t)
                                amp_vals.append(a)
                        if t2_vals:
                            results[sheet] = {'T2': t2_vals, 'amplitude': amp_vals}
                    break
        self.extracted = {'type': 'NMR', 'samples': results}

    # ---- PVT ---- #
    def _extract_pvt(self):
        results = {}
        pvt_cols = ['pressure', 'bo', 'rs', 'gor', 'bg', 'viscosity', 'mu']
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if not any(k in text for k in pvt_cols):
                continue
            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]
                found = [k for k in pvt_cols if any(k in cell for cell in row)]
                if len(found) >= 2:
                    headers = list(df.iloc[i])
                    data = df.iloc[i+1:].reset_index(drop=True)
                    data.columns = range(len(data.columns))
                    sheet_data = {}
                    for j, h in enumerate(headers):
                        for k in pvt_cols:
                            if k in str(h).lower():
                                vals = pd.to_numeric(data.iloc[:, j], errors='coerce').dropna().tolist()
                                if vals:
                                    sheet_data[str(h)] = vals
                    if sheet_data:
                        results[sheet] = sheet_data
                    break
        self.extracted = {'type': 'PVT', 'samples': results}

    # ---- RCAL ---- #
    def _extract_rcal(self):
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if 'permeability' not in text or 'porosity' not in text:
                continue
            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]
                if any('poros' in c for c in row) and any('perm' in c for c in row):
                    headers = list(df.iloc[i])
                    data = df.iloc[i+1:].reset_index(drop=True)
                    data.columns = range(len(data.columns))
                    phi_col   = next((j for j, h in enumerate(headers) if 'poros' in str(h).lower()), None)
                    perm_col  = next((j for j, h in enumerate(headers) if 'perm'  in str(h).lower()), None)
                    depth_col = next((j for j, h in enumerate(headers) if 'depth' in str(h).lower()), None)
                    
                    phi_vals, perm_vals, depth_vals = [], [], []
                    for idx, r in data.iterrows():
                        phi = pd.to_numeric(r[phi_col], errors='coerce') if phi_col is not None else None
                        perm = pd.to_numeric(r[perm_col], errors='coerce') if perm_col is not None else None
                        depth = pd.to_numeric(r[depth_col], errors='coerce') if depth_col is not None else None
                        
                        if pd.isna(phi) or pd.isna(perm):
                            continue
                            
                        phi_vals.append(phi)
                        perm_vals.append(perm)
                        if depth_col is not None:
                            depth_vals.append(depth)
                            
                    sheet_data = {}
                    if phi_vals:
                        sheet_data['porosity'] = phi_vals
                        sheet_data['permeability'] = perm_vals
                        if depth_col is not None:
                            sheet_data['depth'] = depth_vals
                        results[sheet] = sheet_data
                    break
        self.extracted = {'type': 'RCAL', 'samples': results}

    # ---- WETTABILITY ---- #
    def _extract_wettability(self):
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if 'amott' not in text and 'usbm' not in text:
                continue
            # Collect all numeric values with their labels
            sheet_data = {}
            for i in range(len(df)):
                row = df.iloc[i].tolist()
                label = str(row[0]).strip() if pd.notna(row[0]) else ''
                val   = next((v for v in row[1:] if isinstance(v, (int, float)) and not pd.isna(v)), None)
                if label and val is not None:
                    sheet_data[label] = val
            if sheet_data:
                results[sheet] = sheet_data
        self.extracted = {'type': 'WETTABILITY', 'samples': results}

    # ---- POROUS PLATE / CENTRIFUGE Pc ---- #
    def _extract_pc(self):
        results = {}
        for sheet, df in self.raw_data.items():
            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]
                
                is_standard_pc = any('sw' in c for c in row) and any('pc' in c or 'capillary' in c for c in row)
                is_centrifuge = any(kw in c for c in row for kw in ['rpm', 'speed', 'g-force']) and any(kw in c for c in row for kw in ['volume', 'produced', 'cc'])
                
                if is_standard_pc or is_centrifuge:
                    headers = list(df.iloc[i])
                    data = df.iloc[i+1:].reset_index(drop=True)
                    data.columns = range(len(data.columns))
                    
                    if is_standard_pc:
                        x_col = next((j for j, h in enumerate(headers) if 'sw' in str(h).lower()), None)
                        y_col = next((j for j, h in enumerate(headers) if 'pc' in str(h).lower() or 'capillary' in str(h).lower()), None)
                        x_name, y_name = 'Sw', 'Pc'
                    else:
                        x_col = next((j for j, h in enumerate(headers) if any(kw in str(h).lower() for kw in ['rpm', 'speed', 'g-force'])), None)
                        y_col = next((j for j, h in enumerate(headers) if any(kw in str(h).lower() for kw in ['volume', 'produced', 'cc'])), None)
                        x_name, y_name = 'RPM', 'Produced Volume'
                        
                    if x_col is not None and y_col is not None:
                        x_vals = []
                        y_vals = []
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

    # ------------------------------------------------------------------ #
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------ #

    def process(self):
        """Run the full pipeline: read → identify → extract."""
        self.read()
        self.identify()
        self.extract()
        return {
            'data_type':   self.data_type,
            'sheet_names': self.sheet_names,
            'extracted':   self.extracted,
            'row_count':   self._count_rows(self.extracted)
        }

    def _count_rows(self, data: dict) -> int:
        """Helper to count total data points for AI acknowledgment."""
        count = 0
        if isinstance(data, dict):
            for v in data.values():
                count += self._count_rows(v)
        elif isinstance(data, list):
            count += len(data)
        return count


# ------------------------------------------------------------------ #
# SEND TO AI — build the prompt with extracted data
# ------------------------------------------------------------------ #

def build_prompt_for_ai(processed: dict) -> str:
    """
    Takes the output of SCALFileHandler.process() and builds
    a prompt to send to your AI (Gemini, Claude, etc.)
    so it can plot or analyze the data.
    """
    data_type = processed['data_type']
    extracted  = processed['extracted']

    if data_type == 'UNKNOWN':
        return (
            "I could not identify the data type in this file. "
            "Please check the file and re-upload."
        )

    data_json = json.dumps(extracted, indent=2)

    prompt = f"""
You are a petrophysics AI assistant. The engineer has uploaded a SCAL file.
I have already read and extracted the data for you. Do not read the file again.

Data type identified: {data_type}

Extracted data:
{data_json}

Instructions:
1. Plot the appropriate curve for {data_type} data using the extracted values above.
2. Use the correct axis scales and labels as per petroleum engineering standards.
3. After the chart, give 3-5 bullet points of key observations.
4. Do NOT generate or invent any data. Use only what is provided above.
"""
    return prompt
