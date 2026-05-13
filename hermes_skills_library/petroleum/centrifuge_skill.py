import sys
import json
import numpy as np

def calculate_centrifuge_pc(rpm, r1, r2, delta_rho):
    """
    Calculates the inlet face capillary pressure (Pc) from centrifuge parameters.
    
    Pc_inlet = 1.096e-5 * delta_rho * RPM^2 * (r2^2 - r1^2)
    
    rpm: array or scalar of rotational speed (RPM)
    r1: inner radius of the core plug in centrifuge (cm)
    r2: outer radius of the core plug in centrifuge (cm)
    delta_rho: density difference between the two fluids (g/cm3)
    
    Returns: Capillary pressure in psia
    """
    rpm = np.array(rpm)
    # The constant 1.096e-5 converts the standard units to psi
    pc_psia = 1.096e-5 * delta_rho * (rpm**2) * (r2**2 - r1**2)
    return pc_psia

def hassler_brunner_correction(pc_inlet, avg_sw):
    """
    Applies the Hassler-Brunner approximation to convert average saturation
    to inlet face saturation.
    
    Sw(Pc) = Sw_avg + Pc * d(Sw_avg) / d(Pc)
    
    pc_inlet: array of inlet capillary pressures
    avg_sw: array of average water saturations
    """
    pc = np.array(pc_inlet)
    sw_avg = np.array(avg_sw)
    
    if len(pc) < 2:
        return sw_avg
        
    # Numerical differentiation (central difference for interior, forward/backward for edges)
    dsw_dpc = np.gradient(sw_avg, pc)
    
    sw_face = sw_avg + pc * dsw_dpc
    # Clip to valid saturation range
    sw_face = np.clip(sw_face, 0, 1)
    return sw_face

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python centrifuge_skill.py <params_json>"}))
        sys.exit(1)
        
    try:
        params = json.loads(sys.argv[1])
        
        mode = params.get("mode", "pc_only")
        
        if mode in ["pc_only", "full"]:
            rpm = params.get("rpm")
            r1 = params.get("r1")
            r2 = params.get("r2")
            delta_rho = params.get("delta_rho")
            
            if None in [rpm, r1, r2, delta_rho]:
                print(json.dumps({"error": "Missing required centrifuge parameters (rpm, r1, r2, delta_rho)"}))
                sys.exit(1)
                
            pc = calculate_centrifuge_pc(rpm, r1, r2, delta_rho)
            result = {"pc_psia": pc.tolist()}
            
            if mode == "full":
                avg_sw = params.get("avg_sw")
                if avg_sw is not None:
                    sw_face = hassler_brunner_correction(pc, avg_sw)
                    result["sw_face"] = sw_face.tolist()
            
            print(json.dumps(result))
            
        elif mode == "hassler_brunner":
            pc = params.get("pc_psia")
            avg_sw = params.get("avg_sw")
            if None in [pc, avg_sw]:
                print(json.dumps({"error": "Missing pc_psia or avg_sw for Hassler-Brunner"}))
                sys.exit(1)
                
            sw_face = hassler_brunner_correction(pc, avg_sw)
            print(json.dumps({"sw_face": sw_face.tolist()}))
        else:
            print(json.dumps({"error": f"Unknown mode: {mode}"}))
            sys.exit(1)
            
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
