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

import re
from pathlib import Path
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
        """Read ALL sheets in the workbook without filtering by name.

        The previous optimisation that whitelisted sheet names by keyword
        silently dropped sheets named "Sample 1", "Sample 2", etc.
        For SCAL files we cannot afford silent data loss — read everything
        and let the extractor decide what is relevant.
        """
        if self.extension in ('.xlsx', '.xlsm', '.xls', '.ods'):
            engine = (
                'openpyxl' if self.extension in ('.xlsx', '.xlsm')
                else ('xlrd' if self.extension == '.xls' else 'odf')
            )
            xl = pd.ExcelFile(self.file_path, engine=engine)
            self.sheet_names = xl.sheet_names

            for sheet in self.sheet_names:
                self.raw_data[sheet] = pd.read_excel(
                    xl, sheet_name=sheet, header=None
                )

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
            'capillary pressure', 'pore throat', 'washburn', 'saturation'
        ],
        'KR': [
            'kro', 'krw', 'krg', 'relative permeability',
            'end point', 'sor', 'swi', 'sgr', 'water flood', 'kr', 'permeability'
        ],
        'PC': [
            'porous plate', 'centrifuge', 'brine saturation', 'oil-brine', 'air-brine',
            'reservoir conditions', 'rpm', 'speed', 'produced volume', 'cc', 'g-force',
            'capillary pressure', 'drainage', 'imbibition', 'drainge', 'saturation'
        ],
        'FRF': [
            'formation factor', 'formation resistivity factor',
            'cementation', 'tortuosity', '100% brine', 'archie', 'rt', 'ro', 'phi', 'porosity'
        ],
        'RI': [
            'resistivity index', 'saturation exponent',
            'partial saturation', 'rt', 'ro', ' ri ', 'sw', 'saturation'
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
                        weight = 10 if kw in ['rpm', 'centrifuge', 'speed', 'produced volume'] else 1
                        scores[data_type] += weight

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

    # ------------------------------------------------------------------ #
    # MICP HELPERS
    # ------------------------------------------------------------------ #

    # Column header substrings that prove a column is a volume measurement
    # (e.g. "Cumulative Intrusion (mL/g)") and must NEVER be used as saturation.
    _VOL_UNIT_REJECT = frozenset([
        'ml/g', 'cc/g', 'ml/gm', 'cc/gm', 'cm3/g', 'cm³/g',
        'ml/gram', 'cc/gram',
    ])

    # Sheet name fragments that identify aggregate / summary sheets.
    # These are NOT individual rock samples and must not be treated as such.
    _SUMMARY_SHEET_KEYWORDS = frozenset([
        'all data', 'all_data', 'alldata', 'all sheet', 'summary',
        'combined', 'composite', 'total', 'overview', 'aggregate',
        'report', 'master',
    ])

    def _is_summary_sheet(self, sheet_name: str) -> bool:
        """Return True when the sheet name suggests it is a summary/aggregate sheet."""
        s = sheet_name.lower().strip()
        return any(kw in s for kw in self._SUMMARY_SHEET_KEYWORDS)

    def _pick_micp_sat_col(self, headers: list, df_subset: pd.DataFrame = None):
        """
        Return the column index most likely to hold Hg Saturation (% or fraction).

        Scoring (highest wins):
          +100  header contains '%'  — explicit percent marker
          + 80  'hg sat' / 's_hg' / 'shg' literal
          + 60  'cumul' — cumulative column is the gold standard
          + 50  'sat' in header (no volume unit present)
          + 40  'sw' in header
          + 20  'pv' in header (pore-volume fraction, dimensionless)
          + 10  'hg' alone (last-resort fallback)
          −200  'intrusion' without '%' → volume intrusion, NOT saturation
          SKIP  any header containing a volume unit (ml/g, cc/g, …)
          SKIP  any 'incremental'/'incr.'/'delta' header not also labelled 'cumulative'
          REJECT if numerical series looks incremental (if df_subset provided)
        """
        candidates = []
        for j, h in enumerate(headers):
            h_str = str(h).lower().strip()

            # Hard reject: any column whose header contains a volume unit.
            if any(vunit in h_str for vunit in self._VOL_UNIT_REJECT):
                continue

            score = 0
            # ── HARD REJECT 2: incremental headers ──
            is_header_incremental = ('incremental' in h_str or 'incr.' in h_str
                                     or 'delta' in h_str or 'Δ' in h_str)
            is_header_cumulative  = 'cumul' in h_str or 'total' in h_str or 'cum.' in h_str
            if is_header_incremental and not is_header_cumulative:
                continue

            # ── HARD REJECT 3: Numerical incremental check (Data-aware validation) ──
            if df_subset is not None and j < df_subset.shape[1]:
                # Sample the series to see if it's cumulative saturation or incremental delta
                series = pd.to_numeric(df_subset.iloc[:, j], errors='coerce').dropna().values
                if len(series) > 5:
                    net_range = abs(series[-1] - series[0])
                    total_mvmt = np.sum(np.abs(np.diff(series)))
                    # Incremental data sums much larger than its range.
                    # Strict threshold: 1.8x. If total movement is > 1.8x net range, it's not a cumulative saturation curve.
                    if total_mvmt > 1.8 * net_range and net_range > 0.01:
                        continue

            # ── POSITIVE SCORES ──
            if '%' in h_str:                                         score += 100
            if 'cumul' in h_str:                                     score += 60
            if 'hg sat' in h_str or 's_hg' in h_str:               score += 80
            if h_str.replace(' ', '') in ('shg', 's_hg'):           score += 80
            if 'sat' in h_str:                                       score += 50
            if 'sw' in h_str:                                        score += 40
            if 'pv' in h_str and 'intrusion' not in h_str:          score += 20
            if 'hg' in h_str and 'intrusion' not in h_str:          score += 10
            # ── Penalise generic intrusion headers that have no % sign ──
            if 'intrusion' in h_str and '%' not in h_str:           score -= 200

            if score > 0:
                candidates.append((score, j))

        if not candidates:
            return None
        return max(candidates, key=lambda x: x[0])[1]

    # ---- MICP ---- #
    def _extract_micp(self):
        """
        Extract MICP drainage/imbibition curves from every sheet.

        Each result is tagged with:
          sheet_name   — the exact Excel sheet name
          sheet_type   — 'sample' | 'summary'
          sat_column_used — the exact header string chosen for saturation
          sat_is_percent  — True if values appear to be 0-100 %, False if 0-1 fraction

        Summary sheets are still extracted (they may be useful for reference)
        but are clearly flagged so the AI does not treat them as distinct rock samples.
        """
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if not any(kw in text for kw in [
                'mercury', 'hg', 'psia', 'mpa', 'intrusion', 'capillary pressure', 'pc'
            ]):
                continue

            sheet_type = 'summary' if self._is_summary_sheet(sheet) else 'sample'

            for i in range(min(30, len(df))):
                row = [str(v).lower() for v in df.iloc[i] if pd.notna(v)]
                has_press = any(kw in c for c in row for kw in ['press', 'psia', 'mpa', 'pc'])
                has_sat   = any(kw in c for c in row for kw in ['sat', 'hg', 'pv', 'intrusion', 'sw'])
                if not (has_press and has_sat):
                    continue

                headers  = list(df.iloc[i])
                data     = df.iloc[i + 1:].reset_index(drop=True)
                data.columns = range(len(data.columns))

                press_col = next(
                    (j for j, h in enumerate(headers)
                     if any(kw in str(h).lower() for kw in ['press', 'psia', 'mpa', 'pc'])),
                    None
                )
                # FIX 3 — use scored selector with data-aware validation
                sat_col = self._pick_micp_sat_col(headers, data)

                if press_col is None or sat_col is None or press_col == sat_col:
                    continue

                cycle_col = next(
                    (j for j, h in enumerate(headers) if 'cycle' in str(h).lower()), None
                )

                drainage    = {'pressure': [], 'sat_pv': []}
                imbibition  = {'pressure': [], 'sat_pv': []}

                for _, r in data.iterrows():
                    p = pd.to_numeric(r[press_col], errors='coerce')
                    s = pd.to_numeric(r[sat_col],   errors='coerce')
                    if pd.isna(p) or pd.isna(s):
                        continue

                    cycle = str(r[cycle_col]).strip().upper() if cycle_col is not None else 'D'
                    if cycle.startswith('I'):
                        imbibition['pressure'].append(round(float(p), 3))
                        imbibition['sat_pv'].append(round(float(s), 4))
                    else:
                        drainage['pressure'].append(round(float(p), 3))
                        drainage['sat_pv'].append(round(float(s), 4))

                if not (drainage['pressure'] or imbibition['pressure']):
                    continue

                # Detect whether saturation is already a percentage or a fraction
                all_sat = drainage['sat_pv'] + imbibition['sat_pv']
                sat_is_percent = bool(all_sat) and max(all_sat) > 1.5

                # Log whether the chosen column looks incremental (should always be False
                # after the _pick_micp_sat_col fix, but kept for audit transparency).
                chosen_h = str(headers[sat_col]).lower()
                sat_is_incremental = (
                    'incremental' in chosen_h
                    or 'incr.' in chosen_h
                    or 'delta' in chosen_h
                )

                # FIX 2 — tag every result with sheet identity and type
                results[sheet] = {
                    'sheet_name':       sheet,
                    'sheet_type':       sheet_type,
                    'sat_column_used':  str(headers[sat_col]),
                    'sat_is_percent':   sat_is_percent,
                    'sat_is_incremental': sat_is_incremental,
                    'drainage':         drainage,
                    'imbibition':       imbibition,
                }
                break  # found the data block in this sheet; move to next sheet

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
                    if phi_col is not None and f_col is not None and phi_col != f_col:
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
                    if sw_col is not None and ri_col is not None and sw_col != ri_col:
                        sw_vals, ri_vals = [], []
                        for idx, r in data.iterrows():
                            s = pd.to_numeric(r[sw_col], errors='coerce')
                            ri = pd.to_numeric(r[ri_col], errors='coerce')
                            if not pd.isna(s) and not pd.isna(ri):
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
                    if t2_col is not None and amp_col is not None and t2_col != amp_col:
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
                        phi  = pd.to_numeric(r[phi_col],   errors='coerce') if phi_col  is not None else None
                        perm = pd.to_numeric(r[perm_col],  errors='coerce') if perm_col is not None else None
                        depth= pd.to_numeric(r[depth_col], errors='coerce') if depth_col is not None else None

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
                data = df.iloc[i+1:].reset_index(drop=True)
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

    # ------------------------------------------------------------------ #
    # WELL NAME EXTRACTION
    # ------------------------------------------------------------------ #

    def _extract_well_name(self) -> str:
        """
        Identify the well name from sheet headers or the filename.
        Scans for 'Well', 'Field', 'Reservoir', 'Project', etc.
        """
        # ── 1. HEADER SCAN ──
        # Expanded keywords to catch legacy or non-standard reports
        patterns = [
            re.compile(r'well\s*[#:no.]*\s*', re.IGNORECASE),
            re.compile(r'field\s*', re.IGNORECASE),
            re.compile(r'reservoir\s*', re.IGNORECASE),
            re.compile(r'project\s*', re.IGNORECASE),
            re.compile(r'block\s*', re.IGNORECASE),
        ]

        for _sheet, _df in self.raw_data.items():
            # Scan top 15 rows of each sheet
            for i in range(min(15, len(_df))):
                _row = _df.iloc[i].tolist()
                for j, _cell in enumerate(_row):
                    if isinstance(_cell, str):
                        for pat in patterns:
                            if pat.search(_cell):
                                # Check next 3 cells for the value
                                for k in range(j + 1, min(j + 5, len(_row))):
                                    _val = str(_row[k]).strip()
                                    if _val and _val.lower() not in ('#', 'no.', 'name', 'well', 'field', 'nan'):
                                        # Validate value length and content
                                        if 1 < len(_val) < 40 and not _val.lower().startswith('unnamed'):
                                            return _val
        
        # ── 2. FILENAME FALLBACK ──
        _stem = os.path.splitext(os.path.basename(self.file_path))[0]
        # Common well patterns: T1-31, A-12, B_10, etc.
        well_match = re.search(r'([A-Z]{1,3}[-_]?\d{1,4}[A-Z]?)', _stem, re.IGNORECASE)
        if well_match:
            return well_match.group(1).upper()

        # Token based fallback
        for _token in re.split(r'[_\-\s]+', _stem):
            if 3 <= len(_token) <= 15 and re.search(r'[A-Za-z]', _token) and re.search(r'\d', _token):
                return _token

        return "PROVISIONAL WELL"

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
            'row_count':   self._count_rows(self.extracted),
            'well_name':   self._extract_well_name(),
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
    Takes the output of SCALFileHandler.process() and builds a structured
    prompt for the AI so it can analyse and plot the data correctly.

    MICP data is routed through a purpose-built prompt that handles
    summary-sheet disambiguation, correct Pd extraction, and an explicit
    anti-fabrication guardrail for geological interpretation.
    """
    data_type = processed['data_type']
    extracted  = processed['extracted']

    if data_type == 'UNKNOWN':
        return (
            "I could not identify the data type in this file. "
            "Please check the file and re-upload."
        )

    # FIX 2 + FIX 4 — MICP gets a dedicated, guardrailed prompt
    if data_type == 'MICP':
        return _build_micp_prompt(extracted, processed.get('well_name', 'PROVISIONAL WELL'))

    # Generic prompt for all other data types
    data_json = json.dumps(extracted, indent=2)
    return f"""
You are a petrophysics AI assistant. The engineer has uploaded a SCAL file.
I have already read and extracted the data for you. Do not read the file again.

SOURCE WELL: {processed.get('well_name', 'PROVISIONAL WELL')}
Data type identified: {data_type}

Extracted data (each top-level key is the Excel sheet name the data came from):
{data_json}

Instructions:
1. Plot the appropriate curve for {data_type} data using the extracted values above.
2. Use the correct axis scales and labels as per petroleum engineering standards.
3. After the chart, give 3-5 bullet points of key observations.
4. Do NOT generate or invent any data. Use only what is provided above.
5. All data comes from the same well. Do not fabricate geological differences
   between sheets just because values differ — sample-to-sample variation is normal.
"""


def _build_micp_prompt(extracted: dict, well_name: str = "PROVISIONAL WELL") -> str:
    """
    Purpose-built MICP prompt that enforces:
      FIX 2 — summary vs. sample sheet disambiguation
      FIX 4 — anti-hallucination guardrail for geological interpretation
    """
    samples = extracted.get('samples', {})

    sample_sheets  = [k for k, v in samples.items() if isinstance(v, dict) and v.get('sheet_type') == 'sample']
    summary_sheets = [k for k, v in samples.items() if isinstance(v, dict) and v.get('sheet_type') == 'summary']

    sample_list_str  = '\n'.join(f'  - "{s}"' for s in sample_sheets)  or '  (none detected)'
    summary_list_str = '\n'.join(f'  - "{s}"' for s in summary_sheets) or '  (none)'

    data_json = json.dumps(extracted, indent=2)

    return f"""
You are a petrophysics AI assistant performing MICP (Mercury Injection Capillary Pressure) analysis.
The file has already been parsed. The extracted data is below. Do NOT re-read the file.

SOURCE WELL: {well_name}
═══════════════════════════════════════════════════════════
SHEET CLASSIFICATION (determined by sheet name)
═══════════════════════════════════════════════════════════
Individual sample sheets — use ONLY these for per-sample analysis:
{sample_list_str}

Summary / aggregate sheets — these consolidate data across samples.
Do NOT treat them as distinct rock samples or distinct data sources:
{summary_list_str}

═══════════════════════════════════════════════════════════
EXTRACTED DATA  (keyed by exact Excel sheet name)
═══════════════════════════════════════════════════════════
{data_json}

═══════════════════════════════════════════════════════════
MANDATORY ANALYSIS INSTRUCTIONS
═══════════════════════════════════════════════════════════

1. PER-SAMPLE ANALYSIS ONLY
   Analyse and report results individually for each sheet listed under
   "Individual sample sheets" above. Do NOT analyse summary/aggregate
   sheets as independent rock samples. If a summary sheet is present,
   note it exists but do not compare its aggregated values against
   individual sample curves as if they represent different rocks.

2. SATURATION COLUMN VALIDATION
   Each sample entry includes a "sat_column_used" field — the exact
   column header extracted from the file.
   • If "sat_is_percent" is true, values are already in % (0–100). Use as-is.
   • If "sat_is_percent" is false, values are fractional (0–1). Multiply by 100
     before reporting or plotting.
   Report the maximum Hg saturation reached (%) for every sample.

3. ENTRY (THRESHOLD) PRESSURE Pd PER SAMPLE
   For each sample's drainage curve, identify Pd as the pressure at which
   Hg saturation first rises meaningfully (the "knee" of the curve).
   Report Pd explicitly in the units present in the data (psia or MPa).
   State Pd clearly as: "Sample X (sheet: <sheet_name>): Pd = N psia"

4. PORE THROAT SIZE ESTIMATE
   Using the Washburn equation (assuming IFT = 485 dyne/cm, contact angle = 140°):
     r_μm ≈ 107 / Pc_psia
   Categorise dominant pore throats as:
     macro (>10 μm) | meso (1–10 μm) | micro (0.1–1 μm) | nano (<0.1 μm)

5. PLOT
   Generate a semi-log plot:
     X-axis: Hg Saturation (%)  — linear scale, 0 to 100
     Y-axis: Capillary Pressure — log scale
   One curve per individual sample sheet. Use distinct colours. Mark Pd
   for each sample with a vertical dashed line or annotation.

6. ══ ANTI-FABRICATION GUARDRAIL — READ AND ENFORCE ══
   • ALL data comes from the SAME well.
   • Different threshold pressures (Pd) between samples are NORMAL —
     they reflect natural pore-size heterogeneity within the same formation.
   • Do NOT interpret differing Pd values as evidence of different rock
     types, different facies, or different geological formations UNLESS
     the uploaded data explicitly contains depth intervals or lithology
     annotations that support such a conclusion.
   • Do NOT hallucinate geological facies names, formation names, or
     depositional environment descriptions.
   • Confine all geological language strictly to what the numbers directly
     support — e.g. "Sample 3 has a higher Pd (smaller pore throats) than
     Sample 1" is correct. "Sample 3 represents a tighter, lower-quality
     facies from a different stratigraphic interval" is fabrication unless
     depth data is present.
   • Every number you report must be directly traceable to the extracted
     data above. Do not invent, interpolate, or extrapolate values.
"""


# ------------------------------------------------------------------ #
# ROBUST FALLBACK EXTRACTOR (unchanged — do not modify)
# ------------------------------------------------------------------ #

def _detect_data_block(df_raw):
    n_rows, n_cols = df_raw.shape
    if n_rows < 2 or n_cols < 2:
        return None, None, None

    numeric_counts = []
    for i in range(n_rows):
        row = df_raw.iloc[i]
        count = sum(1 for v in row if pd.notna(v) and isinstance(v, (int, float)) and not isinstance(v, bool))
        numeric_counts.append(count)

    for i in range(n_rows - 2):
        if numeric_counts[i] >= 3 and numeric_counts[i+1] >= 3:
            data_start = i
            data_end = data_start
            for j in range(data_start, n_rows):
                if numeric_counts[j] >= 2:
                    data_end = j
                else:
                    if data_end - data_start >= 2:
                        break
            header_row = max(0, data_start - 1)
            return header_row, data_start, data_end
    return None, None, None


def _extract_metadata(df_raw, data_start_idx):
    meta = {}
    patterns = {
        "well":       re.compile(r"well\s*[#:]*", re.IGNORECASE),
        "company":    re.compile(r"company", re.IGNORECASE),
        "analyst":    re.compile(r"analyst", re.IGNORECASE),
        "date":       re.compile(r"\bdate\b", re.IGNORECASE),
        "n_samples":  re.compile(r"no\.?\s*of\s*samples|number of samples", re.IGNORECASE),
        "brine_res":  re.compile(r"brine.*resist", re.IGNORECASE),
        "salinity":   re.compile(r"salinity", re.IGNORECASE),
        "pressure":   re.compile(r"\bpressure\b|overburden", re.IGNORECASE),
        "temperature":re.compile(r"\btemp(?:erature)?\b", re.IGNORECASE),
    }
    scan_rows = min(data_start_idx, 10)
    for i in range(scan_rows):
        row = df_raw.iloc[i].tolist()
        for j, cell in enumerate(row):
            if isinstance(cell, str):
                for field, pat in patterns.items():
                    if pat.search(cell) and field not in meta:
                        for k in range(j+1, min(j+5, len(row))):
                            v = row[k]
                            if pd.notna(v) and (not isinstance(v, str) or v.strip()):
                                meta[field] = v
                                break
    return meta


def _classify_track(headers, data):
    header_str = " ".join(str(h).lower() for h in headers if pd.notna(h))

    if any(k in header_str for k in ["ri", "resistivity index", "sw", "rt", "ro"]) and "i" in header_str:
        return "RI"
    if "formation factor" in header_str or " ff " in header_str or "cementation" in header_str:
        return "FF"
    if any(k in header_str for k in ["s_hg", "mercury", "hg sat", "pc (psia)", "psia"]) and any(k in header_str for k in ["hg", "mercury", "saturation"]):
        return "MICP"
    if "krw" in header_str and "kro" in header_str:
        return "KR"
    if "rpm" in header_str and any(k in header_str for k in ["volume", "cc", "ml", "produced"]):
        return "CENTRIFUGE"
    if "pc" in header_str and "sw" in header_str:
        return "PC"
    if "porosity" in header_str and ("permeability" in header_str or " k " in header_str or "ka" in header_str):
        return "BCA"
    return "UNKNOWN"


def robust_extract_scal(filepath):
    result = {
        "filename": os.path.basename(filepath),
        "engine_used": None,
        "sheets": [],
        "errors": []
    }

    ext = Path(filepath).suffix.lower()
    engines_to_try = []
    if ext == ".xls":
        engines_to_try = ["xlrd"]
    elif ext == ".xlsx" or ext == ".xlsm":
        engines_to_try = ["openpyxl"]
    elif ext == ".xlsb":
        engines_to_try = ["pyxlsb"]
    elif ext in (".csv", ".tsv"):
        engines_to_try = ["csv"]
    else:
        engines_to_try = ["openpyxl", "xlrd", "pyxlsb"]

    xls_obj = None
    sheets_dict = None
    last_err = None
    for eng in engines_to_try:
        try:
            if eng == "csv":
                sep = "," if ext == ".csv" else "\t"
                df = pd.read_csv(filepath, header=None, sep=sep)
                sheets_dict = {"Sheet1": df}
                result["engine_used"] = "csv"
                break
            else:
                sheets_dict = pd.read_excel(filepath, sheet_name=None, header=None, engine=eng)
                result["engine_used"] = eng
                break
        except Exception as e:
            last_err = f"{eng}: {type(e).__name__}: {e}"
            result["errors"].append(last_err)
            continue

    if sheets_dict is None:
        result["errors"].append(f"All parsers failed for {filepath}")
        return result

    for sheet_name, df_raw in sheets_dict.items():
        sheet_info = {
            "name": sheet_name,
            "raw_shape": list(df_raw.shape),
            "metadata": {},
            "data_block": None,
            "track": "UNKNOWN",
            "notes": []
        }

        header_row, data_start, data_end = _detect_data_block(df_raw)
        if data_start is None:
            sheet_info["notes"].append("No numeric data block detected.")
            result["sheets"].append(sheet_info)
            continue

        sheet_info["metadata"] = _extract_metadata(df_raw, data_start)

        headers = df_raw.iloc[header_row].tolist() if header_row >= 0 else [f"col_{i}" for i in range(df_raw.shape[1])]
        data_rows = df_raw.iloc[data_start:data_end+1].values.tolist()
        clean_rows = []
        for row in data_rows:
            clean_row = []
            for v in row:
                if pd.isna(v):
                    clean_row.append(None)
                elif isinstance(v, (int, float, np.integer, np.floating)):
                    clean_row.append(float(v))
                else:
                    clean_row.append(str(v))
            clean_rows.append(clean_row)

        sheet_info["data_block"] = {
            "header_row": int(header_row),
            "data_start": int(data_start),
            "data_end": int(data_end),
            "headers": [str(h) if pd.notna(h) else f"col_{i}" for i, h in enumerate(headers)],
            "n_rows": len(clean_rows),
            "rows": clean_rows,
        }
        sheet_info["track"] = _classify_track(headers, clean_rows)
        result["sheets"].append(sheet_info)

    return result


def extract_file_data(filepath):
    try:
        handler = SCALFileHandler(filepath)
        result = handler.process()
        if result and result.get("row_count", 0) > 0:
            return result
    except Exception as e:
        pass

    robust_result = robust_extract_scal(filepath)
    if any(s.get("data_block") for s in robust_result["sheets"]):
        data_types = [s["track"] for s in robust_result["sheets"] if s.get("data_block") and s["track"] != "UNKNOWN"]
        dt = data_types[0] if data_types else "UNKNOWN"
        return {
            "data_type": dt,
            "sheet_names": [s["name"] for s in robust_result["sheets"]],
            "row_count": sum(s["data_block"]["n_rows"] for s in robust_result["sheets"] if s.get("data_block")),
            "extracted": robust_result,
            "status": "success"
        }
    return {
        "status": "parsing_failed",
        "data_type": "UNKNOWN",
        "sheet_names": [],
        "row_count": 0,
        "extracted": robust_result,
        "filename": robust_result["filename"],
        "engines_tried": [e.split(":")[0] for e in robust_result["errors"]],
        "errors": robust_result["errors"],
    }
