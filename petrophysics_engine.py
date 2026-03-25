import numpy as np
import pandas as pd

class ArchieCalculator:
    """
    Strict Mathematical Logic to rigorously solve Archie's Electrical Equations 
    (m and n) from the master DataFrame.
    """
    @staticmethod
    def _format(val: float) -> float:
        return float(f"{val:.4f}")

    def compute_archie_parameters(self, df: pd.DataFrame) -> dict:
        ff_dataset = df.dropna(subset=['Porosity', 'Formation_Factor']).copy()
        
        if len(ff_dataset) > 1:
            log_poro = np.log10(ff_dataset['Porosity'].astype(float).values)
            log_ff = np.log10(ff_dataset['Formation_Factor'].astype(float).values)
            m_slope, log_a = np.polyfit(log_poro, log_ff, 1)
            cementation_m = -m_slope
            a_tort = 10 ** log_a
        else:
            cementation_m, a_tort = 2.05, 1.0 
            
        ri_dataset = df.dropna(subset=['Brine_Saturation', 'Resistivity_Index']).copy()
        
        if len(ri_dataset) > 1:
            log_sw = np.log10(ri_dataset['Brine_Saturation'].astype(float).values)
            log_ri = np.log10(ri_dataset['Resistivity_Index'].astype(float).values)
            n_slope, _ = np.polyfit(log_sw, log_ri, 1)
            saturation_n = -n_slope
        else:
            saturation_n = 2.0
            
        return {
            "a_tortuosity": self._format(abs(a_tort)),
            "m_cementation": self._format(abs(cementation_m)),
            "n_saturation": self._format(abs(saturation_n))
        }

    def compute_saturation_endpoints(self, df: pd.DataFrame) -> dict:
        ri_dataset = df.dropna(subset=['Brine_Saturation']).copy()
        if len(ri_dataset) > 1:
            sw_array = ri_dataset['Brine_Saturation'].astype(float).values
            swi = np.min(sw_array)
            sor = 1.0 - np.max(sw_array)
        else:
            swi, sor = 0.15, 0.25
            
        if swi + sor > 1.0 or swi < 0.0:
            swi, sor = 0.15, 0.25
            
        return {
            "Swi": self._format(swi),
            "Sor": self._format(abs(sor))
        }
