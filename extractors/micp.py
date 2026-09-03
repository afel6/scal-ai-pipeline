import re
import pandas as pd
import numpy as np
from extractors.base import BaseExtractor
from prc_physics import calculate_washburn_radius

class MICPExtractor(BaseExtractor):
    """
    Extractor class for Mercury Injection Capillary Pressure (MICP) datasets.
    """
    # Column header substrings that prove a column is a volume measurement
    # (e.g. "Cumulative Intrusion (mL/g)") and must NEVER be used as saturation.
    _VOL_UNIT_REJECT = frozenset([
        'ml/g', 'cc/g', 'ml/gm', 'cc/gm', 'cm3/g', 'cm³/g',
        'ml/gram', 'cc/gram',
    ])

    # Sheet name fragments that identify aggregate / summary sheets.
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
            is_header_cumulative  = 'cumul' in h_str or 'cumm' in h_str or 'total' in h_str or 'cum.' in h_str
            if is_header_incremental and not is_header_cumulative:
                continue

            # ── HARD REJECT 3: Numerical incremental check (Data-aware validation) ──
            if df_subset is not None and j < df_subset.shape[1]:
                series = pd.to_numeric(df_subset.iloc[:, j], errors='coerce').dropna().values
                if len(series) < 5:
                    continue
                net_range = abs(series[-1] - series[0])
                total_mvmt = np.sum(np.abs(np.diff(series)))
                if total_mvmt > 1.8 * net_range and net_range > 0.01:
                    continue
                
                # ── HARD REJECT 4: Constant/junk column check ──
                if net_range <= 1e-4:
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
            if 'intrusion' in h_str and '%' not in h_str:           score -= 200

            if score > 0:
                candidates.append((score, j))

        if not candidates:
            return None
        return max(candidates, key=lambda x: x[0])[1]

    def extract(self) -> dict:
        """
        Extract MICP drainage/imbibition curves from every sheet.
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

                # Truncate at first empty or non-numeric row to isolate the main table
                cutoff = len(data)
                for idx_r, r in data.iterrows():
                    first_val = r.iloc[0]
                    if pd.isna(first_val) or (isinstance(first_val, str) and not re.match(r'^\s*[-+]?\d', first_val)):
                        cutoff = idx_r
                        break
                data = data.iloc[:cutoff].reset_index(drop=True)

                press_col = next(
                    (j for j, h in enumerate(headers)
                     if any(kw in str(h).lower() for kw in ['press', 'psia', 'mpa', 'pc'])),
                    None
                )
                sat_col = self._pick_micp_sat_col(headers, data)

                if press_col is None or sat_col is None or press_col == sat_col:
                    continue

                cycle_col = next(
                    (j for j, h in enumerate(headers) if 'cycle' in str(h).lower()), None
                )

                drainage    = {'pressure': [], 'sat_pv': [], 'calculated_pore_radius_microns': []}
                imbibition  = {'pressure': [], 'sat_pv': [], 'calculated_pore_radius_microns': []}
                rows_left_out = []   # Pc <= 0 rows: no Washburn radius exists, the curve says so

                for _, r in data.iterrows():
                    p = pd.to_numeric(r[press_col], errors='coerce')
                    s = pd.to_numeric(r[sat_col],   errors='coerce')
                    if pd.isna(p) or pd.isna(s):
                        continue

                    p_val = float(p)
                    if p_val <= 0:
                        rows_left_out.append(f"Pc <= 0 ({p_val:g} psia, sat {float(s):g}): pore radius undefined (Washburn)")
                        continue
                    r_val = calculate_washburn_radius(p_val)

                    cycle = str(r[cycle_col]).strip().upper() if cycle_col is not None else 'D'
                    if cycle.startswith('I'):
                        imbibition['pressure'].append(round(p_val, 3))
                        imbibition['sat_pv'].append(round(float(s), 4))
                        imbibition['calculated_pore_radius_microns'].append(r_val)
                    else:
                        drainage['pressure'].append(round(p_val, 3))
                        drainage['sat_pv'].append(round(float(s), 4))
                        drainage['calculated_pore_radius_microns'].append(r_val)

                if not (drainage['pressure'] or imbibition['pressure']):
                    continue

                # Detect whether saturation is already a percentage or a fraction
                all_sat = drainage['sat_pv'] + imbibition['sat_pv']
                sat_is_percent = bool(all_sat) and max(all_sat) > 1.5

                chosen_h = str(headers[sat_col]).lower()
                sat_is_incremental = (
                    'incremental' in chosen_h
                    or 'incr.' in chosen_h
                    or 'delta' in chosen_h
                )

                threshold_p = None
                for i_tp in range(min(20, len(df))):
                    row_tp = df.iloc[i_tp].tolist()
                    for j_tp, cell in enumerate(row_tp):
                        if (isinstance(cell, str)
                                and 'threshold' in cell.lower()
                                and 'pressure' in cell.lower()):
                            for k_tp in range(j_tp + 1, min(j_tp + 4, len(row_tp))):
                                v = pd.to_numeric(row_tp[k_tp], errors='coerce')
                                if not pd.isna(v):
                                    threshold_p = round(float(v), 4)
                                    break
                            if threshold_p is not None:
                                break
                    if threshold_p is not None:
                        break

                results[sheet] = {
                    'sheet_name':              sheet,
                    'sheet_type':              sheet_type,
                    'sat_column_used':         str(headers[sat_col]),
                    'sat_is_percent':          sat_is_percent,
                    'sat_is_incremental':      sat_is_incremental,
                    'threshold_pressure_psi':  threshold_p,
                    'drainage':                drainage,
                    'imbibition':              imbibition,
                    'rows_left_out':           rows_left_out,
                }
                break  # found the data block in this sheet; move to next sheet

        self.extracted = {'type': 'MICP', 'samples': results}
        return self.extracted
