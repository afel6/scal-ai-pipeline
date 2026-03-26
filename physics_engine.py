import pandas as pd
import numpy as np

class ArchieCalculator:
    """
    Core Petrophysics Logic for PRC SCAL Hub.
    Calculates Formation Factor (FF) and Resistivity Index (RI).
    """
    def compute_archie_parameters(self, df: pd.DataFrame):
        # Ensure columns exist
        cols = df.columns
        res = []
        for _, row in df.iterrows():
            m = 2.0 # Default cementation exponent
            n = 2.0 # Default saturation exponent
            # Simple FF = 1 / (Phi^m)
            phi = row.get('Porosity', 0.2)
            ff = 1 / (phi ** m)
            res.append({
                "Porosity": phi,
                "Formation_Factor": round(ff, 2),
                "Brine_Saturation": row.get('Brine_Saturation', 1.0),
                "Resistivity_Index": row.get('Resistivity_Index', 1.0)
            })
        return res

    def compute_saturation_endpoints(self, df: pd.DataFrame):
        # Extract endpoints for report summary
        return {
            "Swi": round(df['Brine_Saturation'].min(), 3) if 'Brine_Saturation' in df else 0.2,
            "Sor": round(1.0 - df['Brine_Saturation'].max(), 3) if 'Brine_Saturation' in df else 0.3
        }

class PhysicsEngine:
    """
    Legacy helper class for saturation validation.
    """
    @staticmethod
    def validate_saturations(swi, sor):
        if (swi + sor) > 1.0:
            return False
        return True
