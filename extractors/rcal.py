import pandas as pd
from extractors.base import BaseExtractor

class RCALExtractor(BaseExtractor):
    """
    Extractor class for Routine Core Analysis (RCAL) datasets.
    """
    def extract(self) -> dict:
        """
        Extract routine core porosity/permeability columns.
        """
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
        return self.extracted
