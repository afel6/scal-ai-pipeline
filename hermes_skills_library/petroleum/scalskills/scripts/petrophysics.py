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
    def calculate_rqi_fzi(phi, perm, depth=None, k=3):
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

        # Cluster into k HUs on log10(FZI) space
        log_fzi = np.log10(fzi)
        labels, centers = PetrophysicsSkills._kmeans_1d(log_fzi, k=k)

        # Sort: HU1 = highest FZI (best quality), HU_k = lowest (poorest)
        cluster_means = []
        for j in range(k):
            mask = (labels == j)
            if mask.any():
                cluster_means.append((j, float(fzi[mask].mean())))
            else:
                cluster_means.append((j, -999.0))
        cluster_means.sort(key=lambda x: x[1], reverse=True)
        label_map = {old: rank + 1 for rank, (old, _) in enumerate(cluster_means)}
        hu = np.array([label_map[int(l)] for l in labels])
        
        # Determine dynamic HU names based on count
        if k == 2:
            hu_names = {1: "High Quality", 2: "Low Quality"}
        elif k == 3:
            hu_names = {1: "Excellent", 2: "Moderate", 3: "Poor/Tight"}
        elif k == 4:
            hu_names = {1: "Excellent", 2: "Good", 3: "Moderate", 4: "Poor/Tight"}
        else:
            hu_names = {1: "Excellent", 2: "Very Good", 3: "Good", 4: "Moderate", 5: "Poor/Tight"}
            # Pad any extra clusters
            for i in range(6, k + 1):
                hu_names[i] = f"HU {i} (Tight)"

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
                "hu_quality": hu_names.get(int(hu[i]), f"HU {int(hu[i])}")
            })

        # Build HU summary
        summary = []
        for hu_num in range(1, k + 1):
            mask = hu == hu_num
            if not mask.any():
                continue
            summary.append({
                "hu": hu_num,
                "quality": hu_names.get(hu_num, f"HU {hu_num}"),
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
        for idx in range(len(sorted_c) - 1):
            thresholds[f"hu{idx+1}_hu{idx+2}"] = round(10 ** ((sorted_c[idx] + sorted_c[idx+1]) / 2.0), 4)

        return {
            "status": "success",
            "total_samples": n,
            "samples": samples,
            "summary": summary,
            "thresholds": thresholds
        }

    @staticmethod
    def calculate_klinkenberg(ka, pm=14.7, depth=None):
        """Calculates liquid equivalent permeability (KL) from gas permeability (Ka) using Klinkenberg relation.
        Iteratively solves: f(KL) = KL * (1 + (0.777 * KL**-0.39) / pm) - ka = 0
        """
        ka = np.array(ka, dtype=float)
        n = len(ka)
        
        # If pm is a single float, expand it to an array
        if isinstance(pm, (int, float)):
            pm = np.full(n, float(pm))
        else:
            pm = np.array(pm, dtype=float)
            
        depths = np.array(depth, dtype=float) if depth is not None else np.arange(1, n + 1, dtype=float)
        
        results = []
        for i in range(n):
            k_a = ka[i]
            p_m = pm[i]
            
            # Iterative Newton-Raphson solver for KL
            if k_a <= 0.0 or p_m <= 0.0:
                kl_solved = 0.0
                b = 0.0
            else:
                kl = k_a
                for _ in range(100):
                    b = 0.777 * (kl ** -0.39)
                    f = kl * (1.0 + b / p_m) - k_a
                    df = 1.0 + (0.777 * 0.61 * (kl ** -0.39)) / p_m
                    kl_new = kl - f / df
                    if abs(kl_new - kl) < 1e-6:
                        kl = kl_new
                        break
                    kl = kl_new
                kl_solved = max(0.0, kl)
                b = 0.777 * (kl_solved ** -0.39) if kl_solved > 0 else 0.0
                
            results.append({
                "sample": i + 1,
                "depth": round(float(depths[i]), 2),
                "ka_md": round(float(k_a), 4),
                "pm_psi": round(float(p_m), 2),
                "kl_md": round(float(kl_solved), 4),
                "b_slippage": round(float(b), 4)
            })
            
        return {
            "status": "success",
            "total_samples": n,
            "samples": results
        }

    @staticmethod
    def calculate_retort_saturation(v_w_raw, v_o, v_p, depth=None):
        """Calculates oil/water/gas saturations using Retort Method with a 0.85 water correction."""
        v_w_raw = np.array(v_w_raw, dtype=float)
        v_o = np.array(v_o, dtype=float)
        v_p = np.array(v_p, dtype=float)
        n = len(v_w_raw)
        
        depths = np.array(depth, dtype=float) if depth is not None else np.arange(1, n + 1, dtype=float)
        
        results = []
        for i in range(n):
            vw_raw = v_w_raw[i]
            vo = v_o[i]
            vp = v_p[i]
            
            vw_corr = 0.85 * vw_raw
            vo_corr = 1.01 * vo # standard expansion correction
            
            if vp <= 0.0:
                sw, so, sg = 0.0, 0.0, 0.0
            else:
                sw = vw_corr / vp
                so = vo_corr / vp
                sg = max(0.0, 1.0 - sw - so)
                
            results.append({
                "sample": i + 1,
                "depth": round(float(depths[i]), 2),
                "vp_cc": round(float(vp), 4),
                "vw_raw_cc": round(float(vw_raw), 4),
                "vw_corr_cc": round(float(vw_corr), 4),
                "vo_raw_cc": round(float(vo), 4),
                "vo_corr_cc": round(float(vo_corr), 4),
                "sw_pct": round(float(sw * 100), 2),
                "so_pct": round(float(so * 100), 2),
                "sg_pct": round(float(sg * 100), 2)
            })
            
        return {
            "status": "success",
            "total_samples": n,
            "samples": results
        }

    @staticmethod
    def calculate_dean_stark(v_w, w_pre, w_post, v_p, rho_o=0.8, rho_w=1.0, depth=None):
        """Calculates saturations using Dean-Stark Method (direct water measurement)."""
        v_w = np.array(v_w, dtype=float)
        w_pre = np.array(w_pre, dtype=float)
        w_post = np.array(w_post, dtype=float)
        v_p = np.array(v_p, dtype=float)
        n = len(v_w)
        
        depths = np.array(depth, dtype=float) if depth is not None else np.arange(1, n + 1, dtype=float)
        
        results = []
        for i in range(n):
            vw = v_w[i]
            wpre = w_pre[i]
            wpost = w_post[i]
            vp = v_p[i]
            
            w_loss = max(0.0, wpre - wpost)
            wo = max(0.0, w_loss - vw * rho_w)
            vo = wo / rho_o
            
            if vp <= 0.0:
                sw, so, sg = 0.0, 0.0, 0.0
            else:
                sw = vw / vp
                so = vo / vp
                sg = max(0.0, 1.0 - sw - so)
                
            results.append({
                "sample": i + 1,
                "depth": round(float(depths[i]), 2),
                "vp_cc": round(float(vp), 4),
                "vw_extracted_cc": round(float(vw), 4),
                "w_loss_g": round(float(w_loss), 4),
                "vo_calc_cc": round(float(vo), 4),
                "sw_pct": round(float(sw * 100), 2),
                "so_pct": round(float(so * 100), 2),
                "sg_pct": round(float(sg * 100), 2)
            })
            
        return {
            "status": "success",
            "total_samples": n,
            "samples": results
        }

    @staticmethod
    def calculate_boyles_law_porosity(p1, p2, v1, v_added, v_b, depth=None):
        """Calculates grain volume and porosity using Boyle's Law Helium expansion."""
        p1 = np.array(p1, dtype=float)
        p2 = np.array(p2, dtype=float)
        v_b = np.array(v_b, dtype=float)
        n = len(p1)
        
        depths = np.array(depth, dtype=float) if depth is not None else np.arange(1, n + 1, dtype=float)
        
        results = []
        for i in range(n):
            press1 = p1[i]
            press2 = p2[i]
            vb = v_b[i]
            
            # Vg = V1 + V_added - V1 * (P1 / P2)
            if press2 <= 0.0:
                vg = vb
                vp = 0.0
                phi = 0.0
            else:
                vg = v1 + v_added - v1 * (press1 / press2)
                vg = min(vb, max(0.0, vg))
                vp = max(0.0, vb - vg)
                phi = vp / vb
                
            results.append({
                "sample": i + 1,
                "depth": round(float(depths[i]), 2),
                "p1_psi": round(float(press1), 2),
                "p2_psi": round(float(press2), 2),
                "vb_cc": round(float(vb), 4),
                "vg_cc": round(float(vg), 4),
                "vp_cc": round(float(vp), 4),
                "phi_pct": round(float(phi * 100), 2)
            })
            
        return {
            "status": "success",
            "total_samples": n,
            "samples": results
        }

    @staticmethod
    def calculate_amott_wettability(dsw_s, dsw_d, dso_s, dso_d, depth=None):
        """Calculates Amott Water Index, Amott Oil Index, and Amott-Harvey index."""
        dsw_s = np.array(dsw_s, dtype=float)
        dsw_d = np.array(dsw_d, dtype=float)
        dso_s = np.array(dso_s, dtype=float)
        dso_d = np.array(dso_d, dtype=float)
        n = len(dsw_s)
        
        depths = np.array(depth, dtype=float) if depth is not None else np.arange(1, n + 1, dtype=float)
        
        results = []
        for i in range(n):
            dsws = dsw_s[i]
            dswd = dsw_d[i]
            dsos = dso_s[i]
            dsod = dso_d[i]
            
            tot_w = dsws + dswd
            tot_o = dsos + dsod
            
            iw = dsws / tot_w if tot_w > 0.0 else 0.0
            io = dsos / tot_o if tot_o > 0.0 else 0.0
            iah = iw - io
            
            if iah >= 0.3:
                state = "Water-Wet"
            elif iah <= -0.3:
                state = "Oil-Wet"
            else:
                state = "Neutral / Mixed-Wet"
                
            results.append({
                "sample": i + 1,
                "depth": round(float(depths[i]), 2),
                "iw": round(float(iw), 4),
                "io": round(float(io), 4),
                "iah": round(float(iah), 4),
                "wettability_state": state
            })
            
        return {
            "status": "success",
            "total_samples": n,
            "samples": results
        }

    @staticmethod
    def audit_xrd_mineralogy(minerals, depth=None):
        """Verifies mineral composition sums to 100% and audits for swelling smectite clays."""
        keys = list(minerals.keys())
        first_key = keys[0]
        n = len(minerals[first_key])
        
        depths = np.array(depth, dtype=float) if depth is not None else np.arange(1, n + 1, dtype=float)
        
        results = []
        for i in range(n):
            sample_minerals = {k: float(minerals[k][i]) for k in keys}
            total_sum = sum(sample_minerals.values())
            
            smectite_val = sample_minerals.get("smectite", 0.0)
            smectite_flag = bool(smectite_val > 2.0)
            
            sum_violation = bool(abs(total_sum - 100.0) > 0.5)
            
            results.append({
                "sample": i + 1,
                "depth": round(float(depths[i]), 2),
                "total_sum": round(total_sum, 2),
                "sum_violation": sum_violation,
                "smectite_pct": round(smectite_val, 2),
                "smectite_warning": smectite_flag,
                "composition": {k: round(v, 2) for k, v in sample_minerals.items()}
            })
            
        return {
            "status": "success",
            "total_samples": n,
            "samples": results
        }

    @staticmethod
    def calculate_nmr_t2_distribution(t2_times, amplitudes, cutoff_ms=33.0, depth=None):
        """Calculates BVI and FFI from transverse relaxation NMR distribution amplitudes."""
        t2_times = np.array(t2_times, dtype=float)
        if len(amplitudes) == 0:
            return {"error": "TOOL ERROR: Amplitudes cannot be empty."}
            
        if not isinstance(amplitudes[0], list):
            amplitudes = [amplitudes]
            
        n = len(amplitudes)
        depths = np.array(depth, dtype=float) if depth is not None else np.arange(1, n + 1, dtype=float)
        
        results = []
        for i in range(n):
            amps = np.array(amplitudes[i], dtype=float)
            if len(amps) != len(t2_times):
                continue
                
            bvi = float(amps[t2_times <= cutoff_ms].sum())
            ffi = float(amps[t2_times > cutoff_ms].sum())
            total = bvi + ffi
            
            free_fluid_ratio = ffi / total if total > 0.0 else 0.0
            
            results.append({
                "sample": i + 1,
                "depth": round(float(depths[i]), 2),
                "cutoff_ms": round(float(cutoff_ms), 2),
                "bvi_bound": round(bvi, 4),
                "ffi_free": round(ffi, 4),
                "total_nmr_porosity": round(total, 4),
                "free_fluid_ratio": round(free_fluid_ratio, 4)
            })
            
        return {
            "status": "success",
            "total_samples": len(results),
            "samples": results
        }

    @staticmethod
    def interpret_ct_scan(hu_values, depth=None):
        """Identifies fractures and identifies bulk lithology based on Hounsfield Units (HU)."""
        hu_values = np.array(hu_values, dtype=float)
        n = len(hu_values)
        depths = np.array(depth, dtype=float) if depth is not None else np.arange(1, n + 1, dtype=float)
        
        results = []
        for i in range(n):
            hu = hu_values[i]
            
            is_fracture = bool(hu < 100.0)
            
            if hu > 2500.0:
                lith = "Anhydrite"
            elif 2000.0 <= hu <= 2400.0:
                lith = "Dolomite"
            elif 1800.0 <= hu < 2100.0:
                lith = "Limestone"
            elif 1200.0 <= hu < 1700.0:
                lith = "Sandstone"
            elif 800.0 <= hu < 1400.0:
                lith = "Shale"
            else:
                lith = "Mixed/Unknown"
                
            results.append({
                "sample": i + 1,
                "depth": round(float(depths[i]), 2),
                "ct_hu": round(float(hu), 1),
                "fractured_identified": is_fracture,
                "lithology": lith
            })
            
        return {
            "status": "success",
            "total_samples": n,
            "samples": results
        }

    @staticmethod
    def calculate_supplementary_properties(sg=None, w_init=None, w_acid=None, depth=None):
        """Handles miscellaneous calculations: API Gravity from SG, and Acid Solubility."""
        n = 1
        if sg is not None:
            sg = np.array(sg, dtype=float)
            n = len(sg)
        if w_init is not None:
            w_init = np.array(w_init, dtype=float)
            w_acid = np.array(w_acid, dtype=float)
            n = len(w_init)
            
        depths = np.array(depth, dtype=float) if depth is not None else np.arange(1, n + 1, dtype=float)
        
        results = []
        for i in range(n):
            res = {
                "sample": i + 1,
                "depth": round(float(depths[i]), 2),
            }
            
            if sg is not None:
                s_g = sg[i]
                if s_g > 0:
                    api = 141.5 / s_g - 131.5
                else:
                    api = 0.0
                res["specific_gravity"] = round(float(s_g), 4)
                res["api_gravity"] = round(float(api), 2)
                
            if w_init is not None:
                w_i = w_init[i]
                w_a = w_acid[i]
                sol = ((w_i - w_a) / w_i) * 100.0 if w_i > 0 else 0.0
                carbonate_flag = bool(sol >= 10.0)
                res["initial_weight_g"] = round(float(w_i), 4)
                res["insoluble_weight_g"] = round(float(w_a), 4)
                res["solubility_pct"] = round(float(sol), 2)
                res["carbonate_rock"] = carbonate_flag
                
            results.append(res)
            
        return {
            "status": "success",
            "total_samples": n,
            "samples": results
        }

    @staticmethod
    def calculate_dykstra_lorenz(perm, phi=None, depth=None):
        """Calculates Dykstra-Parsons coefficient (VDP) and Lorenz coefficient (LC) for permeability heterogeneity."""
        # Ensure inputs are clean lists/arrays of identical length and free of NaNs/Nones
        clean_data = []
        n_input = len(perm)
        
        # Check phi
        phi_arr = phi if phi is not None else [0.15] * n_input
        if len(phi_arr) != n_input:
            phi_arr = [0.15] * n_input
            
        # Check depth
        depth_arr = depth if depth is not None else list(range(1, n_input + 1))
        if len(depth_arr) != n_input:
            depth_arr = list(range(1, n_input + 1))
            
        for i in range(n_input):
            k_val = perm[i]
            p_val = phi_arr[i]
            d_val = depth_arr[i]
            
            # Skip if any are None or NaN
            if k_val is None or p_val is None or d_val is None:
                continue
            try:
                kf = float(k_val)
                pf = float(p_val)
                df = float(d_val)
                if np.isnan(kf) or np.isnan(pf) or np.isnan(df):
                    continue
                # Permeability and porosity must be positive (porosity fraction or percent > 0)
                if kf <= 0 or pf < 0:
                    continue
                clean_data.append((kf, pf, df))
            except (ValueError, TypeError):
                continue
                
        if not clean_data:
            return {"status": "error", "message": "No valid positive permeability and porosity data points found."}
            
        # Unpack clean data
        perm_clean = np.array([x[0] for x in clean_data], dtype=float)
        phi_clean = np.array([x[1] for x in clean_data], dtype=float)
        depths_clean = np.array([x[2] for x in clean_data], dtype=float)
        n = len(perm_clean)

        # 1. Dykstra-Parsons Coefficient VDP
        perm_sorted = np.sort(perm_clean)[::-1]
        k50 = np.percentile(perm_clean, 50.0)
        k84_1 = np.percentile(perm_clean, 15.9) # 84.1% cumulative probability in descending list
        vdp = (k50 - k84_1) / k50 if k50 > 0 else 0.0

        if vdp < 0.1:
            hetero_class_vdp = "Extremely Homogeneous"
        elif vdp < 0.3:
            hetero_class_vdp = "Slightly Heterogeneous"
        elif vdp < 0.5:
            hetero_class_vdp = "Moderately Heterogeneous"
        elif vdp < 0.7:
            hetero_class_vdp = "Highly Heterogeneous"
        else:
            hetero_class_vdp = "Extremely Heterogeneous"

        # 2. Lorenz Coefficient LC
        paired = list(zip(perm_clean, phi_clean, depths_clean))
        paired.sort(key=lambda x: (x[0], x[2]), reverse=True)
        
        sorted_k = np.array([x[0] for x in paired])
        sorted_phi = np.array([x[1] for x in paired])
        sorted_depth = np.array([x[2] for x in paired])
        
        cum_thick_frac = np.arange(0, n + 1) / float(n)
        
        cum_cap = np.zeros(n + 1)
        for idx in range(1, n + 1):
            cum_cap[idx] = cum_cap[idx-1] + sorted_k[idx-1]
        cum_cap_frac = cum_cap / cum_cap[-1] if cum_cap[-1] > 0 else cum_cap
        
        lc = (1.0 / n) * np.sum(cum_cap_frac[1:] + cum_cap_frac[:-1]) - 1.0
        lc = max(0.0, min(1.0, lc))

        if lc < 0.1:
            hetero_class_lc = "Homogeneous"
        elif lc < 0.3:
            hetero_class_lc = "Slight Heterogeneity"
        elif lc < 0.6:
            hetero_class_lc = "Moderate Heterogeneity"
        else:
            hetero_class_lc = "High Heterogeneity"

        samples = []
        for i in range(n):
            samples.append({
                "rank": i + 1,
                "depth": round(float(sorted_depth[i]), 2),
                "k_md": round(float(sorted_k[i]), 4),
                "phi_fraction": round(float(sorted_phi[i]), 4),
                "cum_thickness_frac": round(float(cum_thick_frac[i+1]), 4),
                "cum_capacity_frac": round(float(cum_cap_frac[i+1]), 4)
            })

        return {
            "status": "success",
            "vdp": round(float(vdp), 4),
            "k50_md": round(float(k50), 4),
            "k84_1_md": round(float(k84_1), 4),
            "vdp_classification": hetero_class_vdp,
            "lorenz_coefficient": round(float(lc), 4),
            "lorenz_classification": hetero_class_lc,
            "total_samples": n,
            "samples": samples,
            "thresholds": {
                "vdp": round(float(vdp), 4),
                "lorenz_coefficient": round(float(lc), 4)
            }
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
            res = PetrophysicsSkills.calculate_rqi_fzi(
                params["phi"], 
                params["perm"], 
                depth=params.get("depth"), 
                k=params.get("k_groups", 3)
            )
            print(json.dumps(res))
        elif model == "klinkenberg":
            res = PetrophysicsSkills.calculate_klinkenberg(
                params["ka"],
                pm=params.get("pm", 14.7),
                depth=params.get("depth")
            )
            print(json.dumps(res))
        elif model == "retort_saturation":
            res = PetrophysicsSkills.calculate_retort_saturation(
                params["v_w_raw"],
                params["v_o"],
                params["v_p"],
                depth=params.get("depth")
            )
            print(json.dumps(res))
        elif model == "dean_stark":
            res = PetrophysicsSkills.calculate_dean_stark(
                params["v_w"],
                params["w_pre"],
                params["w_post"],
                params["v_p"],
                rho_o=params.get("rho_o", 0.8),
                rho_w=params.get("rho_w", 1.0),
                depth=params.get("depth")
            )
            print(json.dumps(res))
        elif model == "boyles_law_porosity":
            res = PetrophysicsSkills.calculate_boyles_law_porosity(
                params["p1"],
                params["p2"],
                params["v1"],
                params["v_added"],
                params["v_b"],
                depth=params.get("depth")
            )
            print(json.dumps(res))
        elif model == "amott_wettability":
            res = PetrophysicsSkills.calculate_amott_wettability(
                params["dsw_s"],
                params["dsw_d"],
                params["dso_s"],
                params["dso_d"],
                depth=params.get("depth")
            )
            print(json.dumps(res))
        elif model == "xrd_mineralogy":
            res = PetrophysicsSkills.audit_xrd_mineralogy(
                params["minerals"],
                depth=params.get("depth")
            )
            print(json.dumps(res))
        elif model == "nmr_t2_distribution":
            res = PetrophysicsSkills.calculate_nmr_t2_distribution(
                params["t2_times"],
                params["amplitudes"],
                cutoff_ms=params.get("cutoff_ms", 33.0),
                depth=params.get("depth")
            )
            print(json.dumps(res))
        elif model == "ct_scan":
            res = PetrophysicsSkills.interpret_ct_scan(
                params["hu_values"],
                depth=params.get("depth")
            )
            print(json.dumps(res))
        elif model == "supplementary":
            res = PetrophysicsSkills.calculate_supplementary_properties(
                sg=params.get("sg"),
                w_init=params.get("w_init"),
                w_acid=params.get("w_acid"),
                depth=params.get("depth")
            )
            print(json.dumps(res))
        elif model == "dykstra_lorenz":
            res = PetrophysicsSkills.calculate_dykstra_lorenz(
                params["perm"],
                phi=params.get("phi"),
                depth=params.get("depth")
            )
            print(json.dumps(res))
        else:
            print(json.dumps({"error": f"Unknown model '{model}'"}))
            sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
