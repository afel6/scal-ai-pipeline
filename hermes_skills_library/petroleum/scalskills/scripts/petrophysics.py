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
    def _kmeans_1d(data, k=3, max_iter=100):
        """Minimal 1D K-Means using only numpy (no sklearn dependency)."""
        data = np.array(data, dtype=float)
        # Initialize centers via quantile spread
        centers = np.quantile(data, np.linspace(0, 1, k + 2)[1:-1])
        for _ in range(max_iter):
            # Assign each point to nearest center
            dists = np.abs(data[:, None] - centers[None, :])
            labels = np.argmin(dists, axis=1)
            # Update centers
            new_centers = np.array([data[labels == j].mean() if (labels == j).any() else centers[j] for j in range(k)])
            if np.allclose(new_centers, centers, atol=1e-8):
                break
            centers = new_centers
        return labels, centers

    @staticmethod
    def calculate_rqi_fzi(phi, perm, depth=None):
        """Calculates RQI, FZI, and assigns Hydraulic Units (HU) via K-Means on log10(FZI).

        Returns a full structured payload with per-sample rows, HU summary, and
        partition thresholds — designed for the Black Box Fix protocol so that
        every calculated number enters the LLM's context window as visible text.
        """
        phi = np.array(phi, dtype=float)
        perm = np.array(perm, dtype=float)
        n = len(phi)

        # Validation
        errors = []
        for i in range(n):
            if phi[i] <= 0.0 or phi[i] >= 1.0:
                errors.append(f"Row {i+1}: invalid porosity={phi[i]:.6f} (must be 0<phi<1)")
            if perm[i] <= 0.0:
                errors.append(f"Row {i+1}: invalid permeability={perm[i]:.4f} mD (must be >0)")
        if errors:
            return {"error": "TOOL ERROR: Calculation failed due to invalid data points.", "details": errors}

        # Core calculations
        phi_z = phi / (1.0 - phi)
        rqi = 0.0314 * np.sqrt(perm / phi)
        fzi = rqi / phi_z

        # Cluster into 3 HUs on log10(FZI) space
        log_fzi = np.log10(fzi)
        labels, centers = PetrophysicsSkills._kmeans_1d(log_fzi, k=3)

        # Sort: HU1 = highest FZI (best quality), HU3 = lowest (poorest)
        sorted_idx = np.argsort(centers)[::-1]
        label_map = {int(old): new + 1 for new, old in enumerate(sorted_idx)}
        hu = np.array([label_map[int(l)] for l in labels])
        hu_names = {1: "Excellent", 2: "Moderate", 3: "Poor/Tight"}

        # Build per-sample rows
        depths = np.array(depth, dtype=float) if depth is not None else np.arange(1, n + 1, dtype=float)
        samples = []
        for i in range(n):
            samples.append({
                "sample": i + 1,
                "depth": round(float(depths[i]), 2),
                "phi_pct": round(float(phi[i] * 100), 4),
                "perm_md": round(float(perm[i]), 4),
                "phi_z": round(float(phi_z[i]), 6),
                "rqi": round(float(rqi[i]), 4),
                "fzi": round(float(fzi[i]), 4),
                "hu": int(hu[i]),
                "hu_quality": hu_names[int(hu[i])]
            })

        # Build HU summary
        summary = []
        for hu_num in [1, 2, 3]:
            mask = hu == hu_num
            if not mask.any():
                continue
            summary.append({
                "hu": hu_num,
                "quality": hu_names[hu_num],
                "count": int(mask.sum()),
                "avg_phi_pct": round(float(phi[mask].mean() * 100), 2),
                "avg_k_md": round(float(perm[mask].mean()), 2),
                "avg_rqi": round(float(rqi[mask].mean()), 4),
                "avg_fzi": round(float(fzi[mask].mean()), 4),
                "fzi_min": round(float(fzi[mask].min()), 4),
                "fzi_max": round(float(fzi[mask].max()), 4)
            })

        # Partition thresholds (midpoints between sorted centers in log space)
        sorted_c = sorted(centers.tolist(), reverse=True)
        thresholds = {}
        if len(sorted_c) >= 2:
            thresholds["hu1_hu2"] = round(10 ** ((sorted_c[0] + sorted_c[1]) / 2.0), 4)
        if len(sorted_c) >= 3:
            thresholds["hu2_hu3"] = round(10 ** ((sorted_c[1] + sorted_c[2]) / 2.0), 4)

        return {
            "status": "success",
            "total_samples": n,
            "samples": samples,
            "summary": summary,
            "thresholds": thresholds
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
            res = PetrophysicsSkills.calculate_rqi_fzi(params["phi"], params["perm"], depth=params.get("depth"))
            print(json.dumps(res))
        else:
            print(json.dumps({"error": f"Unknown model '{model}'"}))
            sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
