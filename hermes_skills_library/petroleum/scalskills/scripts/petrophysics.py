import numpy as np
import json
import sys
from scipy.stats import linregress

class PetrophysicsSkills:
    @staticmethod
    def calculate_brooks_corey(sw, entry_pressure, lambda_param, swr):
        sw = np.array(sw)
        swe = (sw - swr) / (1 - swr)
        swe = np.clip(swe, 0.001, 1.0)
        pc = entry_pressure * (swe ** (-1/lambda_param))
        krw = swe ** ((2 + 3 * lambda_param) / lambda_param)
        knw = (1 - swe)**2 * (1 - swe**((2 + lambda_param) / lambda_param))
        return {
            "sw": sw.tolist(),
            "pc": pc.tolist(),
            "krw": krw.tolist(),
            "knw": knw.tolist()
        }

    @staticmethod
    def solve_archie(a, m, n, rw, rt, phi):
        phi = np.array(phi)
        rt = np.array(rt)
        f = a / (phi**m)
        sw_n = f * rw / rt
        sw = sw_n**(1/n)
        return {
            "sw": np.clip(sw, 0, 1).tolist(),
            "formation_factor": f.tolist()
        }

    @staticmethod
    def regress_archie_m_a(phi, f):
        """Regresses Archie parameters m and a from Porosity vs Formation Factor"""
        phi = np.array(phi)
        f = np.array(f)
        # Log F = Log a - m * Log phi
        log_phi = np.log10(phi)
        log_f = np.log10(f)
        slope, intercept, r_value, p_value, std_err = linregress(log_phi, log_f)
        m = -slope
        a = 10**intercept
        return {"m": m, "a": a, "r_squared": r_value**2}

    @staticmethod
    def regress_archie_n(sw, ri):
        """Regresses Archie parameter n from Water Saturation vs Resistivity Index"""
        sw = np.array(sw)
        ri = np.array(ri)
        # Log RI = -n * Log Sw
        log_sw = np.log10(sw)
        log_ri = np.log10(ri)
        slope, intercept, r_value, p_value, std_err = linregress(log_sw, log_ri)
        n = -slope
        return {"n": n, "r_squared": r_value**2}

    @staticmethod
    def calculate_rqi_fzi(phi, perm):
        """Calculates Reservoir Quality Index (RQI) and Flow Zone Indicator (FZI)"""
        phi = np.array(phi)
        perm = np.array(perm) # mD
        
        # RQI in microns
        rqi = 0.0314 * np.sqrt(perm / phi)
        # phi_z (pore volume-to-grain volume ratio)
        phi_z = phi / (1 - phi)
        # FZI
        fzi = rqi / phi_z
        
        return {
            "rqi": rqi.tolist(),
            "fzi": fzi.tolist()
        }

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: python petrophysics.py <model> <params_json>"}))
        sys.exit(1)
        
    model = sys.argv[1]
    try:
        params = json.loads(sys.argv[2])
    except:
        print(json.dumps({"error": "Invalid JSON parameters."}))
        sys.exit(1)
        
    try:
        if model == "brooks_corey":
            sw = params.get("sw", np.linspace(params.get("sw_start", 0), 1, 25).tolist())
            res = PetrophysicsSkills.calculate_brooks_corey(
                sw, 
                params.get("entry_pressure", 1.0), 
                params.get("lambda", 2.0), 
                params.get("swr", 0.2)
            )
            print(json.dumps(res))
        elif model == "archie":
            phi = params.get("phi", np.linspace(0.05, 0.35, 10).tolist())
            res = PetrophysicsSkills.solve_archie(
                params.get("a", 1.0), 
                params.get("m", 2.0), 
                params.get("n", 2.0), 
                params.get("rw", 0.1), 
                params.get("rt", 10.0), 
                phi
            )
            print(json.dumps(res))
        elif model == "regress_archie_m_a":
            res = PetrophysicsSkills.regress_archie_m_a(params["phi"], params["f"])
            print(json.dumps(res))
        elif model == "regress_archie_n":
            res = PetrophysicsSkills.regress_archie_n(params["sw"], params["ri"])
            print(json.dumps(res))
        elif model == "rqi_fzi":
            res = PetrophysicsSkills.calculate_rqi_fzi(params["phi"], params["perm"])
            print(json.dumps(res))
        else:
            print(json.dumps({"error": f"Unknown model '{model}'"}))
            sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
