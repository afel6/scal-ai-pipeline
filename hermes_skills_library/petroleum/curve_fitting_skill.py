import numpy as np
import json
import sys
from scipy.optimize import curve_fit

def corey_model(sw, krow_max, n_ow, swr, sor):
    """
    Corey model for oil-water relative permeability.
    """
    # Normalize saturation
    sw_norm = (sw - swr) / (1 - swr - sor)
    sw_norm = np.clip(sw_norm, 0, 1)
    
    krw = sw_norm**n_ow
    krow = krow_max * (1 - sw_norm)**2 # Simplified for demo
    return krw, krow

def fit_corey(sw_data, krw_data, swr_guess=0.2, sor_guess=0.2):
    """
    Fits raw lab data to a Corey model.
    """
    def model_func(sw, n_ow):
        # We hold swr and sor fixed for this simple fit or estimate them
        sw_norm = (sw - swr_guess) / (1 - swr_guess - sor_guess)
        sw_norm = np.clip(sw_norm, 0, 1)
        return sw_norm**n_ow

    popt, _ = curve_fit(model_func, sw_data, krw_data, p0=[2.0])
    return {"n_ow": popt[0], "swr": swr_guess, "sor": sor_guess}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No data provided"}))
        sys.exit(1)
    
    try:
        data = json.loads(sys.argv[1])
        sw = np.array(data.get("sw", []))
        krw = np.array(data.get("krw", []))
        
        if len(sw) < 3:
            print(json.dumps({"error": "Insufficient data points for fitting"}))
            sys.exit(1)
            
        result = fit_corey(sw, krw)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
