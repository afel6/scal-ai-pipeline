import re
import pandas as pd
from extractors.base import BaseExtractor

class FRFExtractor(BaseExtractor):
    """Extractor for Formation Resistivity Factor (FRF)."""
    def extract(self) -> dict:
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if 'formation factor' not in text and 'frf' not in text and 'rt' not in text and 'ro' not in text and 'archie' not in text:
                continue
            for i in range(min(30, len(df))):
                row = [str(v).lower() for df_row in [df.iloc[i]] for v in df_row if pd.notna(v)]
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
        return self.extracted


class RIExtractor(BaseExtractor):
    """Extractor for Resistivity Index (RI)."""
    def extract(self) -> dict:
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if 'resistivity index' not in text and ' ri ' not in text and 'rt' not in text and 'ro' not in text:
                continue
            for i in range(min(30, len(df))):
                row = [str(v).lower() for df_row in [df.iloc[i]] for v in df_row if pd.notna(v)]
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
        return self.extracted


class NMRExtractor(BaseExtractor):
    """Extractor for Nuclear Magnetic Resonance (NMR) T2 distribution."""
    def extract(self) -> dict:
        results = {}
        for sheet, df in self.raw_data.items():
            text = ' '.join(str(v).lower() for v in df.values.flatten() if pd.notna(v))
            if 't2' not in text and 'nmr' not in text:
                continue
            for i in range(min(30, len(df))):
                row = [str(v).lower() for df_row in [df.iloc[i]] for v in df_row if pd.notna(v)]
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
        return self.extracted


class WettabilityExtractor(BaseExtractor):
    """Extractor for Wettability test datasets (Amott-Harvey/USBM)."""
    def extract(self) -> dict:
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
        return self.extracted


class FDAMExtractor(BaseExtractor):
    """Extractor for Formation Damage KW Sensitivity analysis."""
    def extract(self) -> dict:
        results = {}
        for sheet, df in self.raw_data.items():
            for i in range(min(30, len(df))):
                row_lower = [str(v).lower().strip() for v in df.iloc[i] if pd.notna(v)]
                has_kl = any(c == 'kl' for c in row_lower)
                has_pv = any(('pv' in c and 'cum' in c) or 'throughput' in c
                             for c in row_lower)
                if not (has_kl and has_pv):
                    continue

                headers = [str(v).strip() for v in df.iloc[i]]
                data_df  = df.iloc[i + 1:].reset_index(drop=True)
                data_df.columns = range(len(headers))

                kl_col = next(
                    (j for j, h in enumerate(headers) if h == 'KL'),
                    next((j for j, h in enumerate(headers) if h.lower() == 'kl'), None)
                )
                pv_col = next(
                    (j for j, h in enumerate(headers)
                     if 'pv' in h.lower() and 'cum' in h.lower()),
                    next(
                        (j for j, h in enumerate(headers) if 'throughput' in h.lower()),
                        None
                    )
                )

                if kl_col is None or pv_col is None or kl_col == pv_col:
                    continue

                kl_vals, pv_vals = [], []
                for _, r in data_df.iterrows():
                    kl = pd.to_numeric(r[kl_col], errors='coerce')
                    pv = pd.to_numeric(r[pv_col], errors='coerce')
                    if not pd.isna(kl) and not pd.isna(pv):
                        kl_vals.append(round(float(kl), 6))
                        pv_vals.append(round(float(pv), 6))

                if kl_vals:
                    initial_kl = kl_vals[0]
                    final_kl   = kl_vals[-1]
                    pct_change = (
                        round((final_kl - initial_kl) / initial_kl * 100, 2)
                        if initial_kl != 0 else None
                    )
                    results[sheet] = {
                        'KL_mD':           kl_vals,
                        'Cum_PV_injected': pv_vals,
                        'initial_KL_mD':   initial_kl,
                        'final_KL_mD':     final_kl,
                        'KL_change_pct':   pct_change,
                    }
                    break

        self.extracted = {'type': 'FDAM', 'samples': results}
        return self.extracted
