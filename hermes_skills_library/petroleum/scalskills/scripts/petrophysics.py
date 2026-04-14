import numpy as np
import json
import sys

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

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python petrophysics.py <model> <params_json>")
        sys.exit(1)
        
    model = sys.argv[1]
    try:
        params = json.loads(sys.argv[2])
    except:
        print("Error: Invalid JSON parameters.")
        sys.exit(1)
        
    if model == "brooks_corey":
        sw = np.linspace(params.get("sw_start", 0), 1, 25)
        res = PetrophysicsSkills.calculate_brooks_corey(
            sw, 
            params.get("entry_pressure", 1.0), 
            params.get("lambda", 2.0), 
            params.get("swr", 0.2)
        )
        print(json.dumps(res))
    elif model == "archie":
        phi = np.linspace(0.05, 0.35, 10)
        res = PetrophysicsSkills.solve_archie(
            params.get("a", 1.0), 
            params.get("m", 2.0), 
            params.get("n", 2.0), 
            params.get("rw", 0.1), 
            params.get("rt", 10.0), 
            phi
        )
        print(json.dumps(res))
    else:
        print(f"Error: Unknown model '{model}'")
        sys.exit(1)
