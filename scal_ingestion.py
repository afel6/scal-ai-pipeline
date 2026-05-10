import pandas as pd
import glob
import os

class SCALBatchIngestion:
    """
    Ingests massive folders or ZIP files containing highly complex, dirty 
    Excel (.xlsx) or CSV lab exports. Extremely resilient fuzzy logic mapping.
    """
    def __init__(self, target_path: str):
        self.target_path = target_path

    def compile_well_dataframe(self) -> pd.DataFrame:
        """
        Dynamically loops through all extracted files, aggressively hunts for
        complex variations of Petrophysical headers, and cleanly merges them.
        """
        all_files = glob.glob(os.path.join(self.target_path, '**', '*'), recursive=True)
        # Capture strictly Data files
        data_files = [f for f in all_files if f.endswith('.csv') or f.endswith('.xlsx') or f.endswith('.xls')]
        
        master_data = []
        
        for file in data_files:
            try:
                if file.endswith('.csv'):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)
            except Exception as e:
                print(f"Skipping unreadable file block {os.path.basename(file)}: {e}")
                continue
                
            # Aggressive Fuzzy matching logic for arbitrary oilfield spreadsheet designs
            cols = [str(c).strip().lower() for c in df.columns]
            df.columns = cols

            def get_col_data(options):
                for col in df.columns:
                    for opt in options:
                        if opt in col:
                            return df[col]
                return pd.Series([None] * len(df))

            depth_s = get_col_data(['depth', 'ft', 'm md'])
            poro_s = get_col_data(['porosity', 'poro', 'phi', 'ϕ'])
            perm_s = get_col_data(['permeability', 'perm', 'k ', 'klinkenberg', 'kair'])
            ff_s = get_col_data(['ff', 'f.f.', 'formation factor'])
            sw_s = get_col_data(['sw', 'water saturation', 'brine sat'])
            ri_s = get_col_data(['ri', 'r.i.', 'resistivity index'])
            
            # MICP specific headers
            pc_s = get_col_data(['pc', 'capillary pressure', 'pressure (psia)', 'pressure(psia)'])
            shg_s = get_col_data(['shg', 'mercury saturation', 'hgsat', 'shg_frac', 'saturation_hg'])
            shg_imb_s = get_col_data(['shg_imb', 'imb_sat', 'shg_recovery', 'mercury recovery'])
            pc_imb_s = get_col_data(['pc_imb', 'imb_pc', 'imbibition pc'])

            for i in range(len(df)):
                extracted = {
                    "Depth": depth_s.iloc[i] if pd.notna(depth_s.iloc[i]) else 8500.0,
                    "Porosity": poro_s.iloc[i] if pd.notna(poro_s.iloc[i]) else None,
                    "Permeability": perm_s.iloc[i] if pd.notna(perm_s.iloc[i]) else None,
                    "Formation_Factor": ff_s.iloc[i] if pd.notna(ff_s.iloc[i]) else None,
                    "Brine_Saturation": sw_s.iloc[i] if pd.notna(sw_s.iloc[i]) else None,
                    "Resistivity_Index": ri_s.iloc[i] if pd.notna(ri_s.iloc[i]) else None,
                    "Pc": pc_s.iloc[i] if pd.notna(pc_s.iloc[i]) else None,
                    "SHg": shg_s.iloc[i] if pd.notna(shg_s.iloc[i]) else None,
                    "SHg_Imb": shg_imb_s.iloc[i] if pd.notna(shg_imb_s.iloc[i]) else None,
                    "Pc_Imb": pc_imb_s.iloc[i] if pd.notna(pc_imb_s.iloc[i]) else None
                }
                
                # Check if it has any valid oilfield numbers
                metric_values = [v for k, v in extracted.items() if k != "Depth" and v is not None]
                if metric_values and not all(pd.isna(v) for v in metric_values):
                    # Force data sanitization explicitly to standard Floats
                    for k in extracted:
                        if pd.isna(extracted[k]): 
                            extracted[k] = None
                        elif extracted[k] is not None:
                            try:
                                extracted[k] = float(extracted[k])
                                # Standardize porosity to fraction if it was uploaded as percentage (e.g. 22%)
                                if k == "Porosity" and extracted[k] > 1.0:
                                    extracted[k] = extracted[k] / 100.0
                            except:
                                extracted[k] = None
                                
                    master_data.append(extracted)

        if not master_data:
            # We actively crash and report error rather than secretly faking a report
            raise ValueError("Zero matching numerical samples were identified across your spreadsheets! Ensure your columns remotely resemble: Porosity, Permeability, FF, Sw, RI.")
            
        return pd.DataFrame(master_data).dropna(how='all')
