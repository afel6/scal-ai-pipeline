import sys
import json
import numpy as np

def washburn_equation(pressure_psia, contact_angle_deg=140, interfacial_tension=480):
    """
    Converts capillary pressure to pore throat radius using the Washburn Equation.
    r = (2 * gamma * cos(theta)) / Pc
    
    pressure_psia: array of capillary pressures in psia
    contact_angle_deg: contact angle in degrees
    interfacial_tension: interfacial tension in dynes/cm
    
    Returns: array of pore throat radii in microns
    """
    pressure_psia = np.array(pressure_psia)
    
    # Constants
    # 1 psi = 68947.6 dynes/cm2
    conversion_factor = 68947.6 
    pc_dynes = pressure_psia * conversion_factor
    
    # Avoid division by zero
    pc_dynes = np.where(pc_dynes <= 0, 1e-9, pc_dynes)
    
    theta_rad = np.radians(contact_angle_deg)
    
    # Washburn
    # r is in cm
    radius_cm = (2 * interfacial_tension * np.abs(np.cos(theta_rad))) / pc_dynes
    
    # Convert cm to microns (1 cm = 10,000 microns)
    radius_microns = radius_cm * 10000
    
    return radius_microns

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python micp_skill.py <params_json>"}))
        sys.exit(1)
        
    try:
        params = json.loads(sys.argv[1])
        
        pressure = params.get("pressure_psia")
        if pressure is None:
            print(json.dumps({"error": "Missing 'pressure_psia' in input"}))
            sys.exit(1)
            
        contact_angle = params.get("contact_angle_deg", 140)
        ift = params.get("interfacial_tension", 480)
        
        radius = washburn_equation(pressure, contact_angle, ift)
        
        result = {
            "radius_microns": radius.tolist()
        }
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
