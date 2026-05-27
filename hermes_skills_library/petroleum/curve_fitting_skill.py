"""
PRC Relative Permeability Curve Fitting Skill
Simultaneous 6-parameter Brooks-Corey and 10-parameter LET optimisation using
scipy.optimize.minimize (L-BFGS-B) with a combined Krw+Kro SSE objective.
Endpoints (swr, sor, krw_max, kro_max) are part of the free parameter vector
so they are determined from the data, not assumed.
"""
import json
import sys

import numpy as np
from scipy.optimize import minimize


# ── Pure model functions (self-contained, no external imports) ────────────────

def _se(sw: np.ndarray, swr: float, sor: float) -> np.ndarray:
    """Normalised effective saturation, clamped to (ε, 1-ε)."""
    mobile = 1.0 - swr - sor
    if abs(mobile) < 1e-9:
        mobile = 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        se = (sw - swr) / mobile
    return np.clip(se, 1e-9, 1.0 - 1e-9)


def bc_krw(sw: np.ndarray, swr: float, sor: float, krw_max: float, nw: float) -> np.ndarray:
    se = _se(sw, swr, sor)
    kr = krw_max * se ** nw
    kr = np.where(sw <= swr,        0.0,     kr)
    kr = np.where(sw >= 1.0 - sor, krw_max, kr)
    return np.clip(kr, 0.0, None)


def bc_kro(sw: np.ndarray, swr: float, sor: float, kro_max: float, no: float) -> np.ndarray:
    se = _se(sw, swr, sor)
    kr = kro_max * (1.0 - se) ** no
    kr = np.where(sw <= swr,        kro_max, kr)
    kr = np.where(sw >= 1.0 - sor, 0.0,     kr)
    return np.clip(kr, 0.0, None)


def let_krw(sw: np.ndarray, swr: float, sor: float,
            krw_max: float, L: float, E: float, T: float) -> np.ndarray:
    se  = _se(sw, swr, sor)
    num = se ** L
    den = num + E * (1.0 - se) ** T
    with np.errstate(divide="ignore", invalid="ignore"):
        kr = krw_max * np.where(den > 1e-30, num / den, 0.0)
    kr = np.nan_to_num(kr, nan=0.0, posinf=krw_max, neginf=0.0)
    kr = np.where(sw <= swr,        0.0,     kr)
    kr = np.where(sw >= 1.0 - sor, krw_max, kr)
    return np.clip(kr, 0.0, None)


def let_kro(sw: np.ndarray, swr: float, sor: float,
            kro_max: float, L: float, E: float, T: float) -> np.ndarray:
    se  = _se(sw, swr, sor)
    f   = 1.0 - se
    num = f ** L
    den = num + E * se ** T
    with np.errstate(divide="ignore", invalid="ignore"):
        kr = kro_max * np.where(den > 1e-30, num / den, 0.0)
    kr = np.nan_to_num(kr, nan=0.0, posinf=kro_max, neginf=0.0)
    kr = np.where(sw <= swr,        kro_max, kr)
    kr = np.where(sw >= 1.0 - sor, 0.0,     kr)
    return np.clip(kr, 0.0, None)


def _r2(y: np.ndarray, y_hat: np.ndarray) -> float:
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return round(1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0, 4)


# ── Endpoint estimation from raw data ─────────────────────────────────────────

def _estimate_endpoints(sw: np.ndarray, krw: np.ndarray,
                        kro: np.ndarray) -> tuple[float, float, float, float]:
    """Data-driven initial guesses for swr, sor, krw_max, kro_max."""
    # swr: Sw where Krw first exceeds 0.5 % of its peak
    krw_peak = float(krw.max()) if krw.max() > 1e-6 else 1.0
    nonzero_w = krw > 0.005 * krw_peak
    swr = float(sw[nonzero_w][0]) * 0.95 if nonzero_w.any() else float(sw[0])
    swr = float(np.clip(swr, 0.0, 0.6))

    # sor: 1 − Sw where Kro last exceeds 0.5 % of its peak
    kro_peak = float(kro.max()) if kro.max() > 1e-6 else 1.0
    nonzero_o = kro > 0.005 * kro_peak
    if nonzero_o.any():
        sw_last_o = float(sw[nonzero_o][-1]) * 1.05
        sor = float(np.clip(1.0 - sw_last_o, 0.0, 0.5))
    else:
        sor = float(np.clip(1.0 - float(sw[-1]), 0.0, 0.5))

    # Guard: must leave mobile range
    if swr + sor >= 0.90:
        swr, sor = 0.20, 0.15

    krw_max = float(np.clip(krw_peak, 0.01, 1.0))
    kro_max = float(np.clip(kro_peak, 0.01, 1.0))
    return swr, sor, krw_max, kro_max


def _log_estimate_n(sw: np.ndarray, kr: np.ndarray,
                    swr: float, sor: float, kr_max: float, phase: str) -> float:
    """Log-linear initial estimate for the Corey exponent n."""
    mobile = 1.0 - swr - sor
    if abs(mobile) < 1e-9:
        return 2.0
    se = np.clip((sw - swr) / mobile, 1e-9, 1.0)
    if phase == "oil":
        se = 1.0 - se
    mask = (kr > 1e-6) & (se > 1e-6)
    if np.sum(mask) < 2:
        return 2.0
    lse = np.log(se[mask])
    lkr = np.log(kr[mask] / kr_max)
    n = float(-np.dot(lse, lkr) / (np.dot(lse, lse) + 1e-12))
    return float(np.clip(n, 0.5, 10.0))


# ── Brooks-Corey simultaneous optimisation ────────────────────────────────────

def fit_brooks_corey(sw: np.ndarray, krw: np.ndarray,
                     kro: np.ndarray) -> dict:
    """
    6-parameter simultaneous optimisation:
      p = [swr, sor, krw_max, kro_max, nw, no]
    Objective: SSE(Krw) + SSE(Kro) — both phases weighted equally.
    Falls back to initial log-linear estimates if the solver diverges.
    """
    swr0, sor0, krw_max0, kro_max0 = _estimate_endpoints(sw, krw, kro)
    nw0 = _log_estimate_n(sw, krw, swr0, sor0, krw_max0, "water")
    no0 = _log_estimate_n(sw, kro, swr0, sor0, kro_max0, "oil")

    has_kro = kro.max() > 1e-6
    x0 = [swr0, sor0, krw_max0, kro_max0, nw0, no0]
    bounds = [(0.0, 0.60), (0.0, 0.50),
              (0.01, 1.0), (0.01, 1.0),
              (0.10, 15.0), (0.10, 15.0)]

    def _obj(p):
        swr_, sor_, km_w, km_o, nw_, no_ = p
        if swr_ + sor_ >= 0.98 or swr_ < 0 or sor_ < 0:
            return 1e10
        sse = float(np.sum((krw - bc_krw(sw, swr_, sor_, km_w, nw_)) ** 2))
        if has_kro:
            sse += float(np.sum((kro - bc_kro(sw, swr_, sor_, km_o, no_)) ** 2))
        return sse

    try:
        res = minimize(_obj, x0, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-8})
        p = res.x if (res.success or res.fun < _obj(x0)) else x0
    except Exception:
        p = x0

    swr, sor, krw_max, kro_max, nw, no = [float(v) for v in p]
    # Hard clamp after optimisation
    swr     = float(np.clip(swr,     0.0,  0.60))
    sor     = float(np.clip(sor,     0.0,  0.50))
    if swr + sor >= 0.98:
        swr, sor = swr0, sor0
    krw_max = float(np.clip(krw_max, 0.01, 1.0))
    kro_max = float(np.clip(kro_max, 0.01, 1.0))
    nw      = float(np.clip(nw,      0.10, 15.0))
    no      = float(np.clip(no,      0.10, 15.0))

    r2_krw = _r2(krw, bc_krw(sw, swr, sor, krw_max, nw))
    r2_kro = _r2(kro, bc_kro(sw, swr, sor, kro_max, no)) if has_kro else 0.0

    return {
        "success": True, "model": "brooks_corey",
        "swr":     round(swr,     4), "sor":     round(sor,     4),
        "krw_max": round(krw_max, 4), "kro_max": round(kro_max, 4),
        "nw":      round(nw,      4), "no":      round(no,      4),
        "r2_krw":  r2_krw,            "r2_kro":  r2_kro,
    }


# ── LET simultaneous optimisation ─────────────────────────────────────────────

def fit_let(sw: np.ndarray, krw: np.ndarray, kro: np.ndarray) -> dict:
    """
    10-parameter simultaneous optimisation:
      p = [swr, sor, krw_max, kro_max, Lw, Ew, Tw, Lo, Eo, To]
    Objective: SSE(Krw) + SSE(Kro).
    """
    swr0, sor0, krw_max0, kro_max0 = _estimate_endpoints(sw, krw, kro)
    has_kro = kro.max() > 1e-6
    x0 = [swr0, sor0, krw_max0, kro_max0, 1.5, 1.0, 1.5, 1.5, 1.0, 1.5]
    bounds = [
        (0.0, 0.60), (0.0, 0.50),
        (0.01, 1.0), (0.01, 1.0),
        (0.10, 10.0), (0.01, 100.0), (0.10, 10.0),
        (0.10, 10.0), (0.01, 100.0), (0.10, 10.0),
    ]

    def _obj(p):
        swr_, sor_, km_w, km_o, Lw, Ew, Tw, Lo, Eo, To = p
        if swr_ + sor_ >= 0.98 or swr_ < 0 or sor_ < 0:
            return 1e10
        sse = float(np.sum((krw - let_krw(sw, swr_, sor_, km_w, Lw, Ew, Tw)) ** 2))
        if has_kro:
            sse += float(np.sum((kro - let_kro(sw, swr_, sor_, km_o, Lo, Eo, To)) ** 2))
        return sse

    try:
        res = minimize(_obj, x0, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 3000, "ftol": 1e-12, "gtol": 1e-8})
        p = res.x if (res.success or res.fun < _obj(x0)) else x0
    except Exception:
        p = x0

    swr, sor, krw_max, kro_max, Lw, Ew, Tw, Lo, Eo, To = [float(v) for v in p]
    swr     = float(np.clip(swr,    0.0,  0.60))
    sor     = float(np.clip(sor,    0.0,  0.50))
    if swr + sor >= 0.98:
        swr, sor = swr0, sor0
    krw_max = float(np.clip(krw_max, 0.01, 1.0))
    kro_max = float(np.clip(kro_max, 0.01, 1.0))
    Lw  = float(np.clip(Lw,  0.10, 10.0))
    Ew  = float(np.clip(Ew,  0.01, 100.0))
    Tw  = float(np.clip(Tw,  0.10, 10.0))
    Lo  = float(np.clip(Lo,  0.10, 10.0))
    Eo  = float(np.clip(Eo,  0.01, 100.0))
    To  = float(np.clip(To,  0.10, 10.0))

    r2_krw = _r2(krw, let_krw(sw, swr, sor, krw_max, Lw, Ew, Tw))
    r2_kro = _r2(kro, let_kro(sw, swr, sor, kro_max, Lo, Eo, To)) if has_kro else 0.0

    return {
        "success": True, "model": "let",
        "swr":     round(swr,     4), "sor":     round(sor,     4),
        "krw_max": round(krw_max, 4), "kro_max": round(kro_max, 4),
        "Lw": round(Lw, 4), "Ew": round(Ew, 4), "Tw": round(Tw, 4),
        "Lo": round(Lo, 4), "Eo": round(Eo, 4), "To": round(To, 4),
        "r2_krw": r2_krw, "r2_kro": r2_kro,
    }


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No data provided", "success": False}))
        sys.exit(1)

    try:
        data  = json.loads(sys.argv[1])
        model = data.get("model", "brooks_corey")
        sw    = np.asarray(data.get("sw",  []), dtype=float)
        krw   = np.asarray(data.get("krw", []), dtype=float)
        kro   = np.asarray(data.get("kro", []), dtype=float)

        if len(sw) < 3 or len(krw) < 3:
            print(json.dumps({
                "error": "Insufficient data: need ≥ 3 (sw, krw) pairs",
                "success": False,
            }))
            sys.exit(1)

        if not (np.all(np.isfinite(sw)) and np.all(np.isfinite(krw))):
            print(json.dumps({
                "error": "Input data contains NaN or infinite values in sw/krw",
                "success": False,
            }))
            sys.exit(1)

        # Pad kro with zeros if absent (Krw-only datasets)
        if len(kro) != len(sw):
            kro = np.zeros_like(sw)

        # Sort and deduplicate by Sw
        idx = np.argsort(sw)
        sw, krw, kro = sw[idx], krw[idx], kro[idx]
        _, uniq = np.unique(sw, return_index=True)
        sw, krw, kro = sw[uniq], krw[uniq], kro[uniq]

        if model == "let":
            result = fit_let(sw, krw, kro)
        else:
            result = fit_brooks_corey(sw, krw, kro)

        print(json.dumps(result))

    except Exception as exc:
        print(json.dumps({"error": str(exc), "success": False}))
        sys.exit(1)
