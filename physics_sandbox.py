"""Autonomous Physics Sandbox for the PRC SCAL AI Pipeline.

A bounded execution environment in which the agent can fit petrophysical models
(Brooks-Corey relative permeability, Archie's Law, Archie-Waxman-Smits), check
the results against hard physical laws, and *auto-correct* the fit when the first
pass produces anomalies (saturations outside ``[0, 1]``, abnormally crossing
relative-permeability curves, out-of-range Archie exponents).

Two layers ship here:

``PhysicsSandbox``
    The high-level modelling API. Every public ``fit_*`` method runs a
    fit → validate → (auto-correct) → re-validate loop and returns a clean,
    JSON-serialisable payload (parameters, a :class:`physics_validator.PhysicsGuard`
    health block, and ``{"x", "y", "labels"}`` plot coordinates). Validation and
    curve maths are *imported* from the existing engines — no logic is duplicated.

``run_sandboxed``
    A restricted ``exec`` wrapper for ad-hoc expressions. It whitelists ``math``,
    ``numpy`` and ``scipy`` only, blocks imports / filesystem / network / dunder
    access via a static AST audit, and runs the snippet against an injected input
    namespace. This is a *defence-in-depth* convenience, not a security boundary
    against a determined adversary; never feed it fully untrusted code.

Configuration (iteration cap, saturation tolerance) is read from
:data:`config.settings`. Logging uses the project logger; ``print`` is never used.
"""

from __future__ import annotations

import ast
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import curve_fit

from petrophysical_curves import Endpoints, KrCurveFitter, bc_krw, bc_kro
from physics_validator import PhysicsGuard

_logger = logging.getLogger("prc-sandbox")


class PhysicalValidationError(Exception):
    """Raised when an input or output violates an inviolable physical law.

    Distinct from soft :class:`physics_validator.PhysicsGuard` deductions: this
    is reserved for conditions the sandbox cannot legitimately auto-correct
    (e.g. a measured water-saturation array that falls outside ``[0, 1]``).
    """


class SandboxSecurityError(Exception):
    """Raised when :func:`run_sandboxed` rejects a snippet during its AST audit."""


@dataclass
class FitOutcome:
    """Structured result of an auto-correcting model fit.

    Attributes
    ----------
    model:
        Identifier of the fitted model (``"brooks_corey"`` etc.).
    parameters:
        Fitted parameter dictionary (rounded, JSON-safe).
    health:
        The :meth:`physics_validator.PhysicsGuard.generate_health_score` block.
    coordinates:
        ``{"x": [...], "y": [...], "labels": [...]}`` plot payload — rendering is
        left to the presentation layer (see :mod:`visualizer`).
    corrected:
        ``True`` when the auto-correction loop had to revise the initial fit.
    iterations:
        Number of correction passes performed (``0`` when the first fit passed).
    """

    model: str
    parameters: Dict[str, Any]
    health: Dict[str, Any]
    coordinates: Dict[str, List[Any]]
    corrected: bool = False
    iterations: int = 0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Flatten to a plain dict for JSON serialisation / API responses."""
        return {
            "model": self.model,
            "parameters": self.parameters,
            "health": self.health,
            "coordinates": self.coordinates,
            "corrected": self.corrected,
            "iterations": self.iterations,
            "notes": self.notes,
        }


# ── forward physical models (pure functions) ───────────────────────────────────

def archie_formation_factor(phi: np.ndarray, a: float, m: float) -> np.ndarray:
    """Archie Formation Factor ``FF = a · φ^-m``."""
    phi_safe = np.clip(np.asarray(phi, dtype=float), 1e-9, 1.0)
    return a * phi_safe ** (-m)


def archie_resistivity_index(sw: np.ndarray, b: float, n: float) -> np.ndarray:
    """Archie Resistivity Index ``RI = b · Sw^-n``."""
    sw_safe = np.clip(np.asarray(sw, dtype=float), 1e-9, 1.0)
    return b * sw_safe ** (-n)


def waxman_smits_conductivity(
    sw: np.ndarray, n_star: float, *, cw: float, b_coeff: float,
    qv: float, f_star: float,
) -> np.ndarray:
    """Archie-Waxman-Smits bulk conductivity for a shaly sand.

    ``Ct = (Sw^n* · Cw + B · Qv · Sw^(n*-1)) / F*``

    where the second term captures the excess conductivity contributed by clay
    counter-ions (``Qv`` = cation exchange capacity per unit pore volume,
    ``B`` = equivalent counter-ion conductance). Reduces to Archie's clean-sand
    law as ``Qv → 0``.
    """
    sw_safe = np.clip(np.asarray(sw, dtype=float), 1e-9, 1.0)
    if f_star <= 0:
        raise PhysicalValidationError(f"F* must be positive, got {f_star}.")
    clean = sw_safe ** n_star * cw
    shaly = b_coeff * qv * sw_safe ** (n_star - 1.0)
    return (clean + shaly) / f_star


class PhysicsSandbox:
    """Fit-validate-correct engine for core petrophysical relations."""

    # Physical bounds mirrored from PhysicsGuard.validate_archie_parameters so the
    # corrector and the validator agree on what "in range" means.
    _ARCHIE_BOUNDS = {
        "a": (0.5, 1.5), "m": (1.3, 2.5), "b": (0.5, 1.5), "n": (1.5, 2.5),
    }
    _PASSING_GRADES = {"A", "B"}

    def __init__(
        self,
        max_iterations: Optional[int] = None,
        sw_tolerance: Optional[float] = None,
    ) -> None:
        # Pull operational thresholds from config, with explicit-arg override.
        try:
            from config import settings

            self._max_iter = (
                max_iterations if max_iterations is not None
                else settings.SANDBOX_MAX_ITERATIONS
            )
            self._sw_tol = (
                sw_tolerance if sw_tolerance is not None
                else settings.SANDBOX_SW_TOLERANCE
            )
        except Exception:  # pragma: no cover - config absent in minimal envs
            self._max_iter = max_iterations if max_iterations is not None else 12
            self._sw_tol = sw_tolerance if sw_tolerance is not None else 1e-6

    # ── input guards ──────────────────────────────────────────────────────────

    def _assert_saturation_domain(self, sw: np.ndarray, label: str = "Sw") -> None:
        """Reject saturation arrays straying outside ``[0, 1]`` (± tolerance)."""
        arr = np.asarray(sw, dtype=float)
        lo, hi = float(np.min(arr)), float(np.max(arr))
        if lo < -self._sw_tol or hi > 1.0 + self._sw_tol:
            raise PhysicalValidationError(
                f"{label} outside [0, 1]: min={lo:.4f} max={hi:.4f}. "
                "Saturation domain cannot be auto-corrected — check input units."
            )

    # ── Brooks-Corey relative permeability ────────────────────────────────────

    def fit_brooks_corey(
        self,
        sw: Sequence[float],
        krw: Sequence[float],
        kro: Sequence[float],
        swi: float,
        sor: float,
        krw_max: float = 1.0,
        kro_max: float = 1.0,
    ) -> Dict[str, Any]:
        """Fit Brooks-Corey ``nw``/``no`` and guarantee a physical Kr curve.

        The fit reuses :class:`petrophysical_curves.KrCurveFitter`. The fitted
        model curves are validated by :class:`physics_validator.PhysicsGuard`. If
        the health grade is below ``B`` (e.g. the optimiser landed on crossing or
        non-monotone curves), the auto-correction loop re-fits with progressively
        tighter exponent bounds and finally hands off to simulated annealing,
        keeping the best physical result.
        """
        sw_a = np.asarray(sw, dtype=float)
        krw_a = np.asarray(krw, dtype=float)
        kro_a = np.asarray(kro, dtype=float)
        self._assert_saturation_domain(sw_a)

        endpoints = Endpoints(Swi=swi, Sor=sor, Krw_max=krw_max, Kro_max=kro_max)
        fitter = KrCurveFitter(endpoints)
        result = fitter.fit_brooks_corey(sw_a, krw_a, kro_a)

        grid = fitter.generate_grid("brooks_corey", result)
        health = self._score_kr(grid)
        notes: List[str] = []
        iterations = 0
        corrected = False

        if health["grade"] not in self._PASSING_GRADES:
            corrected = True
            grid, health, iterations, fix_notes = self._auto_correct_kr(
                fitter, endpoints, sw_a, krw_a, kro_a, result,
            )
            notes.extend(fix_notes)

        outcome = FitOutcome(
            model="brooks_corey",
            parameters={
                "nw": result.nw, "no": result.no,
                "Swi": endpoints.Swi, "Sor": endpoints.Sor,
                "Krw_max": endpoints.Krw_max, "Kro_max": endpoints.Kro_max,
                "r2_krw": result.r2_krw, "r2_kro": result.r2_kro,
            },
            health=health,
            coordinates=self._kr_coordinates(grid),
            corrected=corrected,
            iterations=iterations,
            notes=notes,
        )
        return outcome.to_dict()

    def _auto_correct_kr(
        self,
        fitter: KrCurveFitter,
        endpoints: Endpoints,
        sw: np.ndarray,
        krw: np.ndarray,
        kro: np.ndarray,
        seed_result,
    ) -> Tuple[Dict[str, List[float]], Dict[str, Any], int, List[str]]:
        """Iteratively recover a physical Kr curve from an anomalous first fit.

        Strategy: sweep a small ladder of monotonic Brooks-Corey exponents (which
        are physical by construction) and keep the curve whose health score is
        highest; escalate to simulated annealing if none reach a passing grade.
        """
        notes: List[str] = []
        best_grid = fitter.generate_grid("brooks_corey", seed_result)
        best_health = self._score_kr(best_grid)
        iterations = 0

        exponent_ladder = [1.5, 2.0, 2.5, 3.0, 4.0]
        for nw in exponent_ladder:
            for no in exponent_ladder:
                if iterations >= self._max_iter:
                    break
                iterations += 1
                grid = {
                    "Sw": fitter._Sw.tolist(),
                    "Krw": [round(float(v), 6) for v in bc_krw(fitter._Sw, endpoints, nw)],
                    "Kro": [round(float(v), 6) for v in bc_kro(fitter._Sw, endpoints, no)],
                }
                health = self._score_kr(grid)
                if health["score"] > best_health["score"]:
                    best_grid, best_health = grid, health
                    notes.append(f"Refit nw={nw}, no={no} → score {health['score']}")
                if health["grade"] in self._PASSING_GRADES:
                    return best_grid, best_health, iterations, notes

        # Last resort: global search via simulated annealing on the lab data.
        if best_health["grade"] not in self._PASSING_GRADES:
            sa_grid, sa_health, sa_used = self._anneal_kr(endpoints, sw, krw, kro)
            iterations += sa_used
            if sa_health["score"] >= best_health["score"]:
                best_grid, best_health = sa_grid, sa_health
                notes.append("Escalated to simulated annealing for global optimum.")

        return best_grid, best_health, iterations, notes

    def _anneal_kr(
        self, endpoints: Endpoints, sw: np.ndarray, krw: np.ndarray, kro: np.ndarray,
    ) -> Tuple[Dict[str, List[float]], Dict[str, Any], int]:
        """Brooks-Corey global fit via the project's simulated-annealing engine."""
        from prc_simulated_annealing import PRCSimulatedAnnealing

        optimizer = PRCSimulatedAnnealing(krw, kro, sw)
        best_params, history = optimizer.optimize(max_iterations=1500)
        krw_max, kro_max, nw, no = best_params
        ep = Endpoints(Swi=endpoints.Swi, Sor=endpoints.Sor,
                       Krw_max=krw_max, Kro_max=kro_max)
        grid_sw = np.linspace(ep.Swi, ep.Sw_max, KrCurveFitter.N_GRID)
        grid = {
            "Sw": grid_sw.tolist(),
            "Krw": [round(float(v), 6) for v in bc_krw(grid_sw, ep, nw)],
            "Kro": [round(float(v), 6) for v in bc_kro(grid_sw, ep, no)],
        }
        return grid, self._score_kr(grid), len(history)

    @staticmethod
    def _score_kr(grid: Dict[str, List[float]]) -> Dict[str, Any]:
        """Run a fresh PhysicsGuard over a Kr grid and return its health block."""
        guard = PhysicsGuard()
        guard.validate_kr(grid["Sw"], grid["Krw"], grid["Kro"])
        return guard.generate_health_score()

    @staticmethod
    def _kr_coordinates(grid: Dict[str, List[float]]) -> Dict[str, List[Any]]:
        """Shape a Kr grid into the decoupled ``{x, y, labels}`` payload."""
        return {
            "x": grid["Sw"],
            "y": [grid["Krw"], grid["Kro"]],
            "labels": ["Krw", "Kro"],
        }

    # ── Archie's Law ──────────────────────────────────────────────────────────

    def fit_archie(
        self,
        x: Sequence[float],
        y: Sequence[float],
        model_type: str = "RI",
    ) -> Dict[str, Any]:
        """Fit Archie parameters and clamp them into physical bounds.

        ``model_type="FF"`` fits ``a``/``m`` from porosity vs Formation Factor;
        ``model_type="RI"`` fits ``b``/``n`` from water saturation vs Resistivity
        Index. A free log-linear fit runs first; if a parameter escapes its
        physical window the corrector re-solves with a bounded least-squares pass.
        """
        x_a = np.asarray(x, dtype=float)
        y_a = np.asarray(y, dtype=float)
        mt = model_type.upper()
        if mt not in {"FF", "RI"}:
            raise ValueError("model_type must be 'FF' or 'RI'.")
        if mt == "RI":
            self._assert_saturation_domain(x_a, label="Sw")

        coeff, exponent = self._fit_archie_loglinear(x_a, y_a, mt)
        notes: List[str] = []
        iterations = 0
        corrected = False

        coeff_key, exp_key = ("a", "m") if mt == "FF" else ("b", "n")
        if not self._archie_in_bounds(coeff, coeff_key) or \
                not self._archie_in_bounds(exponent, exp_key):
            corrected = True
            coeff, exponent, iterations, notes = self._auto_correct_archie(
                x_a, y_a, mt, coeff, exponent,
            )

        params = {coeff_key: round(float(coeff), 4), exp_key: round(float(exponent), 4)}
        health = self._score_archie(mt, params)
        forward = archie_formation_factor if mt == "FF" else archie_resistivity_index
        y_fit = forward(x_a, coeff, exponent)

        outcome = FitOutcome(
            model=f"archie_{mt.lower()}",
            parameters={**params, "r2": self._r2(y_a, y_fit)},
            health=health,
            coordinates={
                "x": [round(float(v), 6) for v in x_a],
                "y": [[round(float(v), 6) for v in y_a],
                      [round(float(v), 6) for v in y_fit]],
                "labels": [f"{mt} (lab)", f"{mt} (fit)"],
            },
            corrected=corrected,
            iterations=iterations,
            notes=notes,
        )
        return outcome.to_dict()

    def _fit_archie_loglinear(
        self, x: np.ndarray, y: np.ndarray, model_type: str
    ) -> Tuple[float, float]:
        """Closed-form log-log regression for the Archie power law.

        ``log y = log(coeff) - exponent · log x`` — slope and intercept give the
        exponent and coefficient directly.
        """
        mask = (x > 1e-9) & (y > 1e-9)
        if np.sum(mask) < 2:
            # Degenerate input: fall back to textbook clean-sand values.
            return (1.0, 2.0)
        log_x = np.log10(x[mask])
        log_y = np.log10(y[mask])
        slope, intercept = np.polyfit(log_x, log_y, 1)
        exponent = -float(slope)
        coeff = float(10.0 ** intercept)
        return coeff, exponent

    def _auto_correct_archie(
        self, x: np.ndarray, y: np.ndarray, model_type: str,
        coeff0: float, exp0: float,
    ) -> Tuple[float, float, int, List[str]]:
        """Bounded re-fit forcing Archie parameters into their physical window."""
        coeff_key, exp_key = ("a", "m") if model_type == "FF" else ("b", "n")
        c_lo, c_hi = self._ARCHIE_BOUNDS[coeff_key]
        e_lo, e_hi = self._ARCHIE_BOUNDS[exp_key]
        forward = archie_formation_factor if model_type == "FF" else archie_resistivity_index

        p0 = [
            float(np.clip(coeff0, c_lo, c_hi)),
            float(np.clip(exp0, e_lo, e_hi)),
        ]
        notes = [
            f"Free fit out of bounds ({coeff_key}={coeff0:.3f}, "
            f"{exp_key}={exp0:.3f}); re-solving within "
            f"[{c_lo}, {c_hi}] / [{e_lo}, {e_hi}]."
        ]
        try:
            popt, _ = curve_fit(
                lambda xx, c, e: forward(xx, c, e),
                x, y, p0=p0, bounds=([c_lo, e_lo], [c_hi, e_hi]), maxfev=10000,
            )
            return float(popt[0]), float(popt[1]), 1, notes
        except Exception as exc:
            # Bounded LS failed to converge — snap the clamped seed instead.
            notes.append(f"Bounded curve_fit did not converge ({exc}); clamped seed used.")
            return p0[0], p0[1], 1, notes

    def _archie_in_bounds(self, value: float, key: str) -> bool:
        lo, hi = self._ARCHIE_BOUNDS[key]
        return lo <= float(value) <= hi

    @staticmethod
    def _score_archie(model_type: str, params: Dict[str, float]) -> Dict[str, Any]:
        """Health block for fitted Archie parameters (fills the other pair as ideal)."""
        guard = PhysicsGuard()
        a = params.get("a", 1.0)
        m = params.get("m", 2.0)
        b = params.get("b", 1.0)
        n = params.get("n", 2.0)
        guard.validate_archie_parameters(a=a, m=m, b=b, n=n)
        return guard.generate_health_score()

    # ── Archie-Waxman-Smits ───────────────────────────────────────────────────

    def fit_waxman_smits(
        self,
        sw: Sequence[float],
        ct: Sequence[float],
        cw: float,
        b_coeff: float,
        qv: float,
        f_star: float,
        n0: float = 2.0,
    ) -> Dict[str, Any]:
        """Fit the Waxman-Smits saturation exponent ``n*`` from a conductivity set.

        Inverts :func:`waxman_smits_conductivity` for ``n*`` given the petrophysical
        constants (``Cw``, ``B``, ``Qv``, ``F*``). The fitted exponent is checked
        against the Archie ``n`` window and clamped if it strays.
        """
        sw_a = np.asarray(sw, dtype=float)
        ct_a = np.asarray(ct, dtype=float)
        self._assert_saturation_domain(sw_a)
        n_lo, n_hi = self._ARCHIE_BOUNDS["n"]

        def _forward(s: np.ndarray, n_star: float) -> np.ndarray:
            return waxman_smits_conductivity(
                s, n_star, cw=cw, b_coeff=b_coeff, qv=qv, f_star=f_star
            )

        notes: List[str] = []
        corrected = False
        try:
            popt, _ = curve_fit(_forward, sw_a, ct_a, p0=[n0],
                                bounds=(1.0, 4.0), maxfev=10000)
            n_star = float(popt[0])
        except Exception as exc:
            n_star = n0
            corrected = True
            notes.append(f"Fit failed ({exc}); fell back to n*={n0}.")

        if not (n_lo <= n_star <= n_hi):
            corrected = True
            clamped = float(np.clip(n_star, n_lo, n_hi))
            notes.append(f"n*={n_star:.3f} outside [{n_lo}, {n_hi}]; clamped to {clamped}.")
            n_star = clamped

        ct_fit = _forward(sw_a, n_star)
        guard = PhysicsGuard()
        guard.validate_archie_parameters(a=1.0, m=2.0, b=1.0, n=n_star)
        health = guard.generate_health_score()

        outcome = FitOutcome(
            model="archie_waxman_smits",
            parameters={
                "n_star": round(n_star, 4), "Cw": cw, "B": b_coeff,
                "Qv": qv, "F_star": f_star, "r2": self._r2(ct_a, ct_fit),
            },
            health=health,
            coordinates={
                "x": [round(float(v), 6) for v in sw_a],
                "y": [[round(float(v), 6) for v in ct_a],
                      [round(float(v), 6) for v in ct_fit]],
                "labels": ["Ct (lab)", "Ct (Waxman-Smits fit)"],
            },
            corrected=corrected,
            notes=notes,
        )
        return outcome.to_dict()

    # ── shared stats ──────────────────────────────────────────────────────────

    @staticmethod
    def _r2(y: np.ndarray, y_hat: np.ndarray) -> float:
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        return round(1.0 - ss_res / ss_tot, 4) if ss_tot > 1e-12 else 0.0


# ── restricted execution sandbox ───────────────────────────────────────────────

# Whitelisted builtins — pure, side-effect-free helpers only. No open/exec/eval/
# __import__/input/compile. Resolved from the real builtins module so the lookup
# is independent of whether __builtins__ is exposed as a module or a dict.
import builtins as _builtins

_SAFE_BUILTIN_NAMES = (
    "abs", "min", "max", "round", "sum", "len", "range", "enumerate", "zip",
    "map", "filter", "float", "int", "bool", "list", "dict", "tuple", "set",
    "pow", "sorted", "reversed", "all", "any", "divmod", "str",
)
_SAFE_BUILTINS: Dict[str, Any] = {
    name: getattr(_builtins, name) for name in _SAFE_BUILTIN_NAMES
}

_FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "globals",
    "locals", "vars", "getattr", "setattr", "delattr", "exit", "quit",
    "breakpoint", "memoryview", "help",
}


class _SandboxAuditor(ast.NodeVisitor):
    """Static AST walker that rejects imports, dunder access and unsafe calls."""

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        raise SandboxSecurityError("import statements are not allowed in the sandbox.")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        raise SandboxSecurityError("import statements are not allowed in the sandbox.")

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr.startswith("__"):
            raise SandboxSecurityError(
                f"access to dunder attribute '{node.attr}' is blocked."
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if node.id in _FORBIDDEN_NAMES:
            raise SandboxSecurityError(f"use of '{node.id}' is blocked in the sandbox.")
        self.generic_visit(node)


def run_sandboxed(
    source: str,
    inputs: Optional[Dict[str, Any]] = None,
    result_var: str = "result",
) -> Any:
    """Execute a restricted Python snippet against an injected input namespace.

    Parameters
    ----------
    source:
        Python source. May reference the whitelisted modules ``math``, ``np``
        (numpy) and ``scipy`` plus any keys of ``inputs``. It must assign its
        answer to ``result_var``.
    inputs:
        Values exposed as globals to the snippet (e.g. measured arrays).
    result_var:
        Name the snippet writes its output to (default ``"result"``).

    Returns
    -------
    Any
        The value bound to ``result_var`` after execution.

    Raises
    ------
    SandboxSecurityError
        If the static audit rejects the snippet (imports, dunder access, unsafe
        builtins).
    PhysicalValidationError
        If the snippet executes but never assigns ``result_var``.

    Notes
    -----
    Safety is enforced by (1) a static AST audit and (2) a stripped globals dict
    exposing only whitelisted builtins/modules. This blocks the common escape
    routes (filesystem, network, arbitrary imports) but is **not** a hardened
    jail — do not run code from untrusted third parties through it.
    """
    import scipy  # local import: keeps module load light and scopes the exposure

    tree = ast.parse(source, mode="exec")
    _SandboxAuditor().visit(tree)

    safe_globals: Dict[str, Any] = {
        "__builtins__": _SAFE_BUILTINS,
        "math": math,
        "np": np,
        "numpy": np,
        "scipy": scipy,
    }
    if inputs:
        safe_globals.update(inputs)

    safe_locals: Dict[str, Any] = {}
    compiled = compile(tree, filename="<physics-sandbox>", mode="exec")
    exec(compiled, safe_globals, safe_locals)  # noqa: S102 - sandboxed by design

    if result_var in safe_locals:
        return safe_locals[result_var]
    if result_var in safe_globals:
        return safe_globals[result_var]
    raise PhysicalValidationError(
        f"sandboxed snippet did not assign '{result_var}'."
    )
