# petrophysical_curves.py
# PRC SCAL Pipeline — Petrophysical Curve Engine
# Implements Modified Brooks-Corey, LET, and Capillary Pressure models
# with endpoint normalization, PCHIP smoothing, and physics validation.

import numpy as np
from scipy.optimize import curve_fit
from scipy.interpolate import PchipInterpolator
from dataclasses import dataclass, field
from typing import Optional

# ── DATA CLASSES ───────────────────────────────────────────────────────────────

@dataclass
class Endpoints:
    """Irreducible saturations and endpoint permeabilities."""
    Swi:     float          # connate water saturation
    Sor:     float          # residual oil saturation
    Krw_max: float = 1.0   # Kr_water  at Sw = 1 − Sor
    Kro_max: float = 1.0   # Kr_oil    at Sw = Swi

    def __post_init__(self):
        if not (0.0 <= self.Swi < 1.0):
            raise ValueError(f"Swi={self.Swi} must be in [0, 1)")
        if not (0.0 <= self.Sor < 1.0):
            raise ValueError(f"Sor={self.Sor} must be in [0, 1)")
        if self.Swi + self.Sor >= 1.0:
            raise ValueError(f"Swi + Sor = {self.Swi+self.Sor:.3f} must be < 1")
        if not (0.0 < self.Krw_max <= 1.0):
            raise ValueError("Krw_max must be in (0, 1]")
        if not (0.0 < self.Kro_max <= 1.0):
            raise ValueError("Kro_max must be in (0, 1]")

    @property
    def Sw_max(self) -> float:
        return 1.0 - self.Sor

    @property
    def mobile_range(self) -> float:
        return 1.0 - self.Swi - self.Sor


@dataclass
class BrooksCoreyResult:
    nw: float; no: float
    endpoints:     Endpoints
    r2_krw:        float = 0.0
    r2_kro:        float = 0.0
    rmse_krw:      float = 0.0
    rmse_kro:      float = 0.0


@dataclass
class LETResult:
    Lw: float; Ew: float; Tw: float
    Lo: float; Eo: float; To: float
    endpoints:     Endpoints
    r2_krw:        float = 0.0
    r2_kro:        float = 0.0
    rmse_krw:      float = 0.0
    rmse_kro:      float = 0.0


@dataclass
class PcBrooksCoreyResult:
    Pd:     float   # displacement (entry) pressure [psi or bar]
    lam:    float   # pore size distribution index λ
    r2:     float = 0.0
    rmse:   float = 0.0


@dataclass
class ValidationResult:
    is_valid:         bool
    crossover_sw:     Optional[float]
    crossover_kr:     Optional[float]
    wettability:      str
    mono_krw:         bool
    mono_kro:         bool
    warnings:         list = field(default_factory=list)
    errors:           list = field(default_factory=list)
    metrics:          dict = field(default_factory=dict)


# ── PURE MODEL FUNCTIONS ───────────────────────────────────────────────────────

def _Se(Sw: np.ndarray, Swi: float, Sor: float) -> np.ndarray:
    """Normalised saturation, clamped to (ε, 1−ε) to prevent 0^n = 0 edge issues."""
    return np.clip((Sw - Swi) / (1.0 - Swi - Sor), 1e-9, 1.0 - 1e-9)


def bc_krw(Sw: np.ndarray, ep: Endpoints, nw: float) -> np.ndarray:
    """Brooks-Corey Krw = Krw_max · Se^nw with hard endpoint enforcement."""
    kr = ep.Krw_max * _Se(Sw, ep.Swi, ep.Sor) ** nw
    kr = np.where(Sw <= ep.Swi,    0.0,        kr)
    kr = np.where(Sw >= ep.Sw_max, ep.Krw_max, kr)
    return np.clip(kr, 0.0, None)


def bc_kro(Sw: np.ndarray, ep: Endpoints, no: float) -> np.ndarray:
    """Brooks-Corey Kro = Kro_max · (1−Se)^no with hard endpoint enforcement."""
    kr = ep.Kro_max * (1.0 - _Se(Sw, ep.Swi, ep.Sor)) ** no
    kr = np.where(Sw <= ep.Swi,    ep.Kro_max, kr)
    kr = np.where(Sw >= ep.Sw_max, 0.0,        kr)
    return np.clip(kr, 0.0, None)


def let_krw(Sw: np.ndarray, ep: Endpoints, L: float, E: float, T: float) -> np.ndarray:
    """LET Krw: Se^L / (Se^L + E·(1−Se)^T)."""
    Se = _Se(Sw, ep.Swi, ep.Sor)
    num = Se ** L
    kr  = ep.Krw_max * num / (num + E * (1.0 - Se) ** T)
    kr  = np.where(Sw <= ep.Swi,    0.0,        kr)
    kr  = np.where(Sw >= ep.Sw_max, ep.Krw_max, kr)
    return np.clip(kr, 0.0, None)


def let_kro(Sw: np.ndarray, ep: Endpoints, L: float, E: float, T: float) -> np.ndarray:
    """LET Kro: (1−Se)^L / ((1−Se)^L + E·Se^T)."""
    Se = _Se(Sw, ep.Swi, ep.Sor)
    f   = 1.0 - Se
    num = f ** L
    kr  = ep.Kro_max * num / (num + E * Se ** T)
    kr  = np.where(Sw <= ep.Swi,    ep.Kro_max, kr)
    kr  = np.where(Sw >= ep.Sw_max, 0.0,        kr)
    return np.clip(kr, 0.0, None)


def bc_pc(Sw: np.ndarray, Swi: float, Pd: float, lam: float) -> np.ndarray:
    """Brooks-Corey Pc = Pd · Se^(−1/λ). Se = (Sw−Swi)/(1−Swi)."""
    Se = np.clip((Sw - Swi) / (1.0 - Swi), 1e-6, 1.0)
    return Pd * Se ** (-1.0 / lam)


# ── STATISTICS ────────────────────────────────────────────────────────────────

def _r2(y: np.ndarray, y_hat: np.ndarray) -> float:
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0


def _rmse(y: np.ndarray, y_hat: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - y_hat) ** 2)))


# ── Kr CURVE FITTER ────────────────────────────────────────────────────────────

class KrCurveFitter:
    """
    Fits Brooks-Corey and LET models to SCAL lab Kr data.
    """

    N_GRID = 100

    def __init__(self, endpoints: Endpoints):
        self.ep   = endpoints
        self._Sw  = np.linspace(endpoints.Swi, endpoints.Sw_max, self.N_GRID)

    def smooth(
        self,
        Sw_raw: np.ndarray,
        Kr_raw: np.ndarray,
        phase:  str = "water",
    ) -> tuple[np.ndarray, np.ndarray]:
        pairs = np.column_stack([Sw_raw, Kr_raw])
        pairs = pairs[np.argsort(pairs[:, 0])]
        Sw_u, idx = np.unique(pairs[:, 0], return_index=True)
        Kr_u = np.clip(pairs[idx, 1], 0.0, None)
        mask = (Sw_u >= self.ep.Swi) & (Sw_u <= self.ep.Sw_max)
        Sw_u, Kr_u = Sw_u[mask], Kr_u[mask]
        if len(Sw_u) < 2:
            return self._Sw.copy(), np.zeros_like(self._Sw)
        pchip     = PchipInterpolator(Sw_u, Kr_u, extrapolate=False)
        Kr_smooth = np.nan_to_num(pchip(self._Sw), nan=0.0)
        Kr_smooth = np.clip(Kr_smooth, 0.0, None)
        if phase == "water":
            Kr_smooth = np.maximum.accumulate(Kr_smooth)
        else:
            Kr_smooth = np.minimum.accumulate(Kr_smooth[::-1])[::-1]
        return self._Sw.copy(), Kr_smooth

    def fit_brooks_corey(self, Sw: np.ndarray, Krw: np.ndarray, Kro: np.ndarray) -> BrooksCoreyResult:
        ep    = self.ep
        valid = (Sw > ep.Swi) & (Sw < ep.Sw_max)
        if not np.any(valid): return BrooksCoreyResult(nw=2.0, no=2.0, endpoints=ep)
        def _log_estimate(Se_v, Kr_v, Kr_max):
            mask = (Kr_v > 1e-6) & (Se_v > 1e-6)
            if np.sum(mask) < 2: return 2.0
            lSe, lKr = np.log(Se_v[mask]), np.log(Kr_v[mask] / Kr_max)
            n = float(-np.dot(lSe, lKr) / (np.dot(lSe, lSe) + 1e-12))
            return np.clip(n, 0.5, 10.0)
        Se_v  = _Se(Sw[valid], ep.Swi, ep.Sor)
        nw_0  = _log_estimate(Se_v, Krw[valid], ep.Krw_max)
        no_0  = _log_estimate(1.0 - Se_v, Kro[valid], ep.Kro_max)
        try:
            popt, _ = curve_fit(lambda s, n: bc_krw(s, ep, n), Sw[valid], Krw[valid], p0=[nw_0], bounds=(0.1, 15.0))
            nw = float(popt[0])
        except: nw = nw_0
        try:
            popt, _ = curve_fit(lambda s, n: bc_kro(s, ep, n), Sw[valid], Kro[valid], p0=[no_0], bounds=(0.1, 15.0))
            no = float(popt[0])
        except: no = no_0
        Krw_h, Kro_h = bc_krw(Sw, ep, nw), bc_kro(Sw, ep, no)
        return BrooksCoreyResult(nw=round(nw,4), no=round(no,4), endpoints=ep, r2_krw=round(_r2(Krw, Krw_h),4), r2_kro=round(_r2(Kro, Kro_h),4))

    def fit_let(self, Sw: np.ndarray, Krw: np.ndarray, Kro: np.ndarray) -> LETResult:
        ep = self.ep
        valid = (Sw > ep.Swi) & (Sw < ep.Sw_max)
        if not np.any(valid): return LETResult(1.5,1.0,1.5,1.5,1.0,1.5,ep)
        p0, bounds = [1.5, 1.0, 1.5], ([0.1, 0.01, 0.1], [10.0, 100.0, 10.0])
        try: pw, _ = curve_fit(lambda s,L,E,T: let_krw(s,ep,L,E,T), Sw[valid], Krw[valid], p0=p0, bounds=bounds)
        except: pw = p0
        try: po, _ = curve_fit(lambda s,L,E,T: let_kro(s,ep,L,E,T), Sw[valid], Kro[valid], p0=p0, bounds=bounds)
        except: po = p0
        Lw, Ew, Tw = [round(float(v), 4) for v in pw]
        Lo, Eo, To = [round(float(v), 4) for v in po]
        Krw_h, Kro_h = let_krw(Sw, ep, Lw, Ew, Tw), let_kro(Sw, ep, Lo, Eo, To)
        return LETResult(Lw=Lw, Ew=Ew, Tw=Tw, Lo=Lo, Eo=Eo, To=To, endpoints=ep, r2_krw=round(_r2(Krw, Krw_h), 4), r2_kro=round(_r2(Kro, Kro_h), 4))

    def generate_grid(self, model: str, params) -> dict:
        Sw = self._Sw
        if model == "brooks_corey":
            Krw, Kro = bc_krw(Sw, self.ep, params.nw), bc_kro(Sw, self.ep, params.no)
        else:
            Krw, Kro = let_krw(Sw, self.ep, params.Lw, params.Ew, params.Tw), let_kro(Sw, self.ep, params.Lo, params.Eo, params.To)
        fmt = lambda arr: [round(float(v), 6) for v in arr]
        return {"Sw": fmt(Sw), "Krw": fmt(Krw), "Kro": fmt(Kro)}

    def validate(self, Sw: np.ndarray, Krw: np.ndarray, Kro: np.ndarray) -> ValidationResult:
        ep = self.ep
        warns, errs = [], []
        dw, do = np.diff(Krw), np.diff(Kro)
        mono_w, mono_o = bool(np.all(dw >= -1e-4)), bool(np.all(do <= 1e-4))
        if not mono_w: warns.append("Krw non-monotone.")
        if not mono_o: warns.append("Kro non-monotone.")
        diff = Krw - Kro
        sc = np.where(np.diff(np.sign(diff)))[0]
        csw = ckr = None
        if len(sc):
            i = sc[0]
            x1, x2, d1, d2 = Sw[i], Sw[i+1], diff[i], diff[i+1]
            csw = float(x1 - d1 * (x2 - x1) / (d2 - d1 + 1e-12))
            ckr = float(np.interp(csw, Sw, Krw))
        swm = (ep.Swi + ep.Sw_max) / 2.0
        wet = "indeterminate"
        if csw:
            if csw < swm - 0.1: wet = "oil-wet"
            elif csw > swm + 0.1: wet = "water-wet"
            else: wet = "mixed-wet"
        return ValidationResult(is_valid=len(errs)==0, crossover_sw=csw, crossover_kr=ckr, wettability=wet, mono_krw=mono_w, mono_kro=mono_o, warnings=warns, errors=errs)

    def to_plot_json(self, Sw_raw, Krw_raw, Kro_raw, model="brooks_corey", fit_result=None) -> dict:
        validation = self.validate(Sw_raw, Krw_raw, Kro_raw)
        grid = self.generate_grid(model, fit_result) if fit_result else None
        def _pts(S, K): return [{"x": round(float(s), 4), "y": round(float(k), 4)} for s, k in zip(S, K)]
        curves = [
            {"name": "Krw (Lab)", "data": _pts(Sw_raw, Krw_raw), "color": "#38bdf8", "showLine": False, "showPoints": True, "yId": "left"},
            {"name": "Kro (Lab)", "data": _pts(Sw_raw, Kro_raw), "color": "#fb923c", "showLine": False, "showPoints": True, "yId": "right"},
        ]
        if grid:
            label = model.replace("_", " ").title()
            curves += [
                {"name": f"Krw ({label})", "data": _pts(grid["Sw"], grid["Krw"]), "color": "#0ea5e9", "showLine": True, "showPoints": False, "yId": "left"},
                {"name": f"Kro ({label})", "data": _pts(grid["Sw"], grid["Kro"]), "color": "#f97316", "showLine": True, "showPoints": False, "yId": "right"},
            ]
        return {
            "title": "Relative Permeability — Kr vs Sw",
            "xAxis": {"label": "Water Saturation Sw"},
            "yAxis": {"label": "Krw"}, "yAxis2": {"label": "Kro"},
            "dualAxis": True, "curves": curves,
            "metadata": {
                "endpoints": {"Swi": self.ep.Swi, "Sor": self.ep.Sor, "Krw_max": self.ep.Krw_max, "Kro_max": self.ep.Kro_max},
                "validation": {"is_valid": validation.is_valid, "wettability": validation.wettability, "crossover": {"Sw": validation.crossover_sw, "Kr": validation.crossover_kr}, "warnings": validation.warnings, "errors": validation.errors},
                "fit_params": {"model": model.title(), "nw": getattr(fit_result, 'nw', 0), "no": getattr(fit_result, 'no', 0)} if model=="brooks_corey" else {}
            }
        }
