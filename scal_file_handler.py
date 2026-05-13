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
                if any(kw in s_lower for kw in ['scal', 'core', 'data', 'test', 'result', 'analysis', 'summary']):
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
            'mercury', 'hg', 'intrusion', 'psia', 'threshold pressure',
            'drainage', 'imbibition', 'cumulative intrusion',
            'capillary pressure', 'pore throat', 'washburn'
        ],
        'KR': [
            'kro', 'krw', 'krg', 'relative permeability',
            'end point', 'sor', 'swi', 'sgr', 'water flood', 'kr'
        ],
        'PC': [
            'porous plate', 'centrifuge', 'brine saturation',
            'oil-brine', 'air-brine', 'reservoir conditions'
        ],
        'FRF': [
            'formation factor', 'formation resistivity factor',
            'cementation', 'tortuosity', '100% brine', 'archie'
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
        """
        Libyan PRC format:
          - Sheets named 'Sample 1', 'Sample 2', etc.
          - Data starts at row 21 (0-indexed)
          - col 1 = Pressure (psia)
          - col 2 = Cycle (D / I)
          - col 7 = Cumulative Hg saturation (% pore volume)
          - Row 10 col with first float > 1 = threshold pressure
        """
        sample_sheets = [
            s for s in self.sheet_names
            if 'sample' in s.lower() and s.lower() != 'all data'
        ]

        samples = {}
        for sheet in sample_sheets:
            df = self.raw_data[sheet]

            # Threshold pressure
            thresh = None
            try:
                row10 = df.iloc[10].tolist()
                for v in row10:
                    if isinstance(v, (int, float)) and not pd.isna(v) and v > 1:
                        thresh = round(float(v), 2)
                        break
            except Exception:
                pass

            drainage = {'pressure': [], 'sat_pv': []}
            imbibition = {'pressure': [], 'sat_pv': []}

            for i in range(21, len(df)):
                try:
                    row = df.iloc[i].tolist()
                    pressure = row[1]
                    cycle    = row[2]
                    sat_pv   = row[7]

                    if not isinstance(pressure, (int, float)) or pd.isna(pressure):
                        continue
                    if cycle not in ('D', 'I'):
                        continue
                    sat_pv = float(sat_pv) if isinstance(sat_pv, (int, float)) and not pd.isna(sat_pv) else 0.0

                    target = drainage if cycle == 'D' else imbibition
                    target['pressure'].append(round(float(pressure), 3))
                    target['sat_pv'].append(round(sat_pv, 4))
                except Exception:
                    continue

            samples[sheet] = {
                'threshold_pressure': thresh,
                'drainage':           drainage,
                'imbibition':         imbibition,
            }

        self.extracted = {'type': 'MICP', 'samples': samples}

    # ---- RELATIVE PERMEABILITY ---- #
    def _extract_kr(self):
        """
        Look for columns: Sw (or Sg), Kro, Krw (or Krg)
        Works across any sheet that has these headers.
        """
        results = {}
        kr_keywords = {'sw', 'sg', 'kro', 'krw', 'krg', 'kr'}

        for sheet, df in self.raw_data.items():
            # Find header row (first row where ≥2 kr keywords appear)
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
            data_df.columns = headers

            # Map columns
            col_map = {}
            for col in data_df.columns:
                if 'sw' in col:   col_map['Sw']  = col
                if 'sg' in col:   col_map['Sg']  = col
                if 'kro' in col:  col_map['K Kro'] = col
                if 'kro' in col:  col_map['Kro'] = col
                if 'krw' in col:  col_map['Krw'] = col
                if 'krg' in col:  col_map['Krg'] = col

            # Extract numeric rows
            extracted_cols = {}
            for name, col in col_map.items():
                vals = pd.to_numeric(data_df[col], errors='coerce').dropna().tolist()
                if vals:
                    extracted_cols[name] = vals

            if extracted_cols:
                results[sheet] = extracted_cols

        self.extracted = {'type': 'KR', 'samples': results}

    # ---- FORMATION RESISTIVITY FACTOR ---- #
    def _extract_frf(self):
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if 'formation factor' not in text and 'frf' not in text:
                continue
            # Find porosity and F columns
            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]
                if any('poros' in c for c in row) and any('factor' in c or ' f' == c for c in row):
                    headers = list(df.iloc[i])
                    data = df.iloc[i+1:].reset_index(drop=True)
                    data.columns = range(len(data.columns))
                    phi_col = next((j for j, h in enumerate(headers) if 'poros' in str(h).lower()), None)
                    f_col   = next((j for j, h in enumerate(headers) if 'factor' in str(h).lower() or str(h).strip().upper() == 'F'), None)
                    if phi_col is not None and f_col is not None:
                        phi = pd.to_numeric(data.iloc[:, phi_col], errors='coerce').dropna().tolist()
                        f   = pd.to_numeric(data.iloc[:, f_col],   errors='coerce').dropna().tolist()
                        results[sheet] = {'porosity': phi, 'F': f}
                    break
        self.extracted = {'type': 'FRF', 'samples': results}

    # ---- RESISTIVITY INDEX ---- #
    def _extract_ri(self):
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if 'resistivity index' not in text and ' ri ' not in text:
                continue
            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]
                if any('sw' in c for c in row) and any('ri' in c or 'index' in c for c in row):
                    headers = list(df.iloc[i])
                    data = df.iloc[i+1:].reset_index(drop=True)
                    data.columns = range(len(data.columns))
                    sw_col = next((j for j, h in enumerate(headers) if 'sw' in str(h).lower()), None)
                    ri_col = next((j for j, h in enumerate(headers) if 'ri' in str(h).lower() or 'index' in str(h).lower()), None)
                    if sw_col is not None and ri_col is not None:
                        sw = pd.to_numeric(data.iloc[:, sw_col], errors='coerce').dropna().tolist()
                        ri = pd.to_numeric(data.iloc[:, ri_col], errors='coerce').dropna().tolist()
                        results[sheet] = {'Sw': sw, 'RI': ri}
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
                        t2  = pd.to_numeric(data.iloc[:, t2_col],  errors='coerce').dropna().tolist()
                        amp = pd.to_numeric(data.iloc[:, amp_col], errors='coerce').dropna().tolist()
                        results[sheet] = {'T2': t2, 'amplitude': amp}
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
                    sheet_data = {}
                    if phi_col  is not None:
                        sheet_data['porosity']     = pd.to_numeric(data.iloc[:, phi_col],  errors='coerce').dropna().tolist()
                    if perm_col is not None:
                        sheet_data['permeability'] = pd.to_numeric(data.iloc[:, perm_col], errors='coerce').dropna().tolist()
                    if depth_col is not None:
                        sheet_data['depth']        = pd.to_numeric(data.iloc[:, depth_col],errors='coerce').dropna().tolist()
                    if sheet_data:
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
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if 'porous plate' not in text and 'centrifuge' not in text:
                continue
            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]
                if any('sw' in c for c in row) and any('pc' in c or 'capillary' in c for c in row):
                    headers = list(df.iloc[i])
                    data = df.iloc[i+1:].reset_index(drop=True)
                    data.columns = range(len(data.columns))
                    sw_col = next((j for j, h in enumerate(headers) if 'sw' in str(h).lower()), None)
                    pc_col = next((j for j, h in enumerate(headers) if 'pc' in str(h).lower() or 'capillary' in str(h).lower()), None)
                    if sw_col is not None and pc_col is not None:
                        sw = pd.to_numeric(data.iloc[:, sw_col], errors='coerce').dropna().tolist()
                        pc = pd.to_numeric(data.iloc[:, pc_col], errors='coerce').dropna().tolist()
                        results[sheet] = {'Sw': sw, 'Pc': pc}
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
        }


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
