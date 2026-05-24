import pandas as pd
from extractors.base import BaseExtractor

class KRExtractor(BaseExtractor):
    """
    Extractor class for Relative Permeability (KR) curves.
    """
    def extract(self) -> dict:
        """
        Look for columns: Sw (or Sg), Kro, Krog, Krw (or Krg).
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
            units_detected = {}
            for j, col in enumerate(headers):
                is_pct = '%' in col or 'percent' in col
                if 'sw' in col:
                    col_map['Sw']   = j
                    units_detected['Sw']   = 'percent' if is_pct else 'fraction'
                elif 'sg' in col:
                    col_map['Sg']   = j
                    units_detected['Sg']   = 'percent' if is_pct else 'fraction'
                elif 'krog' in col:          # check krog before kro to avoid substring clash
                    col_map['Krog'] = j
                    units_detected['Krog'] = 'percent' if is_pct else 'fraction'
                elif 'kro' in col:
                    col_map['Kro']  = j
                    units_detected['Kro']  = 'percent' if is_pct else 'fraction'
                elif 'krw' in col:
                    col_map['Krw']  = j
                    units_detected['Krw']  = 'percent' if is_pct else 'fraction'
                elif 'krg' in col:
                    col_map['Krg']  = j
                    units_detected['Krg']  = 'percent' if is_pct else 'fraction'

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

            # Normalise any percent-expressed columns to fraction (0-1)
            for k in list(extracted_cols.keys()):
                if units_detected.get(k) == 'percent':
                    extracted_cols[k] = [
                        round(v / 100.0, 6) if v is not None else None
                        for v in extracted_cols[k]
                    ]
                    units_detected[k] = 'fraction (normalised from percent)'

            clean_extracted = {k: v for k, v in extracted_cols.items() if any(val is not None for val in v)}
            if clean_extracted:
                clean_extracted['units_detected'] = units_detected
                results[sheet] = clean_extracted

        self.extracted = {'type': 'KR', 'samples': results}
        return self.extracted
