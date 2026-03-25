import numpy as np

class PRCThermodynamics:
    """
    Comprehensive Physics Engine executing advanced Reservoir Thermodynamics 
    for Special Core Analysis (SCAL) conforming to Libyan oil standards.
    """
    @staticmethod
    def calculate_capillary_pressure(porosity: float, permeability: float, interfacial_tension=30.0) -> list:
        """
        Uses the J-Leverett Function to correlate discrete Capillary Pressure (Pc) 
        arrays mapped against the mobile saturation limits.
        """
        if porosity <= 0 or permeability <= 0:
            return []
            
        pc_array = []
        se_steps = np.linspace(0.01, 0.99, 20) 
        
        for se in se_steps:
            # J = (Pc / (sigma * cos(theta))) * sqrt(k / phi)
            j_func = 0.3 * (se ** -0.5) 
            
            # Pc = J * sigma * sqrt(phi / k)
            pc = j_func * interfacial_tension * np.sqrt(porosity / permeability)
            pc_array.append({
                "Se": float(f"{se:.3f}"),
                "Pc_psi": float(f"{pc:.2f}")
            })
            
        return pc_array

    @staticmethod
    def calculate_wettability(water_displaced: float, oil_displaced: float) -> str:
        """
        Calculates the Amott-Harvey displacement wettability scale.
        """
        index = water_displaced - oil_displaced
        if index > 0.3: return "Strongly Water-Wet"
        if index < -0.3: return "Strongly Oil-Wet"
        return "Neutral / Mixed-Wet"
