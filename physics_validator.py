import numpy as np


class PhysicsEngineError(Exception):
    pass


# ── PHYSICS GUARD ─────────────────────────────────────────────────────────────
# Real-time validation gate that accumulates rule violations across validate_*
# calls, then emits a Health Score and structured audit block for the UI.

class PhysicsGuard:
    """
    Stateful validator for a single dataset. Call validate_kr() or validate_micp(),
    then call generate_health_score() to get the audit result.

    Scoring:
      HIGH violation  → −15 pts each  (monotonicity, impossible values)
      MEDIUM violation → −5 pts each  (soft endpoint warnings)
      Score = max(0, 100 − total_deduction)
      Grade: A ≥ 95 | B ≥ 80 | C ≥ 60 | F < 60
    """

    _HIGH_DEDUCTION   = 15
    _MEDIUM_DEDUCTION = 5

    def __init__(self):
        self._violations: list[dict]  = []
        self._rules_checked: int      = 0

    # ── internal helpers ──────────────────────────────────────────────────────

    def _flag(self, rule: str, detail: str, severity: str = "HIGH") -> None:
        self._violations.append({"rule": rule, "severity": severity, "detail": detail})

    def _check(self, passed: bool, rule: str, detail: str, severity: str = "HIGH") -> None:
        """Increment rule counter; flag if not passed."""
        self._rules_checked += 1
        if not passed:
            self._flag(rule, detail, severity)

    # ── public validators ─────────────────────────────────────────────────────

    def validate_kr(self, sw, krw, kro) -> "PhysicsGuard":
        """
        Seven physical rules for a relative permeability dataset.

        Args:
            sw:  water saturation array (fraction, 0–1)
            krw: relative permeability to water array
            kro: relative permeability to oil array

        Rules:
          1. Krw monotone non-decreasing in Sw
          2. Kro monotone non-increasing in Sw
          3. Krw ∈ [0, 1]
          4. Kro ∈ [0, 1]
          5. Krw at max Sw ≤ 1.0
          6. Krw(Swi) ≈ 0  (immobile water at connate)
          7. Kro(1−Sor) ≈ 0  (immobile oil at residual)
        """
        sw_a  = np.asarray(sw,  dtype=float)
        krw_a = np.asarray(krw, dtype=float)
        kro_a = np.asarray(kro, dtype=float)

        idx   = np.argsort(sw_a)
        sw_s  = sw_a[idx]
        krw_s = krw_a[idx]
        kro_s = kro_a[idx]

        # 1 — Krw monotonicity
        n_krw_viol = int(np.sum(np.diff(krw_s) < -1e-4))
        self._check(
            n_krw_viol == 0,
            "KRW_MONOTONICITY",
            f"Krw decreases at {n_krw_viol} point(s) as Sw increases — "
            "violates water-phase flow continuity.",
        )

        # 2 — Kro monotonicity
        n_kro_viol = int(np.sum(np.diff(kro_s) > 1e-4))
        self._check(
            n_kro_viol == 0,
            "KRO_MONOTONICITY",
            f"Kro increases at {n_kro_viol} point(s) as Sw increases — "
            "violates oil-phase flow continuity.",
        )

        # 3 — Krw range
        self._check(
            bool(np.all(krw_s >= -1e-6) and np.all(krw_s <= 1.0 + 1e-6)),
            "KRW_RANGE",
            f"Krw outside [0, 1]: min={krw_s.min():.4f}  max={krw_s.max():.4f}",
        )

        # 4 — Kro range
        self._check(
            bool(np.all(kro_s >= -1e-6) and np.all(kro_s <= 1.0 + 1e-6)),
            "KRO_RANGE",
            f"Kro outside [0, 1]: min={kro_s.min():.4f}  max={kro_s.max():.4f}",
        )

        # 5 — Endpoint guard: Krw at max Sw
        self._check(
            float(krw_s[-1]) <= 1.0 + 1e-4,
            "KRW_ENDPOINT",
            f"Krw at maximum Sw = {krw_s[-1]:.4f} exceeds 1.0 — physically impossible.",
        )

        # 6 — Zero endpoint: Krw at Swi
        self._check(
            float(krw_s[0]) <= 0.01,
            "KRW_ZERO_AT_SWI",
            f"Krw(Swi) = {krw_s[0]:.4f} ≠ 0 — water should be immobile at "
            "irreducible saturation (Swi).",
            severity="MEDIUM",
        )

        # 7 — Zero endpoint: Kro at 1−Sor
        self._check(
            float(kro_s[-1]) <= 0.01,
            "KRO_ZERO_AT_SOR",
            f"Kro(1−Sor) = {kro_s[-1]:.4f} ≠ 0 — oil should be immobile at "
            "residual saturation (Sor).",
            severity="MEDIUM",
        )

        return self

    def validate_micp(self, pc, hg_sat) -> "PhysicsGuard":
        """
        Four physical rules for a Mercury Injection Capillary Pressure dataset.

        Args:
            pc:     capillary pressure array (psia), drainage cycle
            hg_sat: mercury saturation array (fraction 0–1)

        Rules:
          1. All Pc values must be positive (drainage = mercury injection)
          2. Entry pressure (first Pc > 0.1 psia where Hg_sat > 1%) must be positive
          3. Hg saturation must be monotone non-decreasing with increasing Pc
          4. Hg saturation ∈ [0, 1]
        """
        pc_a  = np.asarray(pc,     dtype=float)
        shg_a = np.asarray(hg_sat, dtype=float)

        idx   = np.argsort(pc_a)
        pc_s  = pc_a[idx]
        shg_s = shg_a[idx]

        # 1 — All Pc positive
        n_neg = int(np.sum(pc_s <= 0))
        self._check(
            n_neg == 0,
            "MICP_NEGATIVE_PC",
            f"{n_neg} Pc value(s) ≤ 0 psia — drainage capillary pressure "
            "must be strictly positive throughout the intrusion cycle.",
        )

        # 2 — Entry pressure positive
        entry_mask = shg_s > 0.01
        pe = float(pc_s[entry_mask][0]) if entry_mask.any() else float(pc_s[0])
        self._check(
            pe > 0,
            "MICP_ENTRY_PRESSURE",
            f"Entry pressure Pe = {pe:.2f} psia ≤ 0 — must be positive "
            "for mercury intrusion to occur.",
        )

        # 3 — Hg saturation monotone non-decreasing with Pc
        n_mono_viol = int(np.sum(np.diff(shg_s) < -1e-4))
        self._check(
            n_mono_viol == 0,
            "MICP_SATURATION_MONOTONICITY",
            f"Mercury saturation decreases at {n_mono_viol} point(s) as Pc "
            "increases — non-physical drainage curve (check for imbibition data "
            "mixed into drainage column).",
        )

        # 4 — Hg saturation range
        self._check(
            bool(np.all(shg_s >= -1e-6) and np.all(shg_s <= 1.0 + 1e-6)),
            "MICP_SAT_RANGE",
            f"Hg saturation outside [0, 1]: "
            f"min={shg_s.min():.4f}  max={shg_s.max():.4f}",
            severity="MEDIUM",
        )

        # 5 — Detect if the saturation column appears to be incremental (delta), not cumulative.
        #     Incremental data has many near-zero or negative consecutive differences,
        #     and the running sum over the series is much larger than the max single value.
        total_range = float(shg_s[-1] - shg_s[0])
        running_sum = float(np.sum(np.abs(np.diff(shg_s))))
        # If the sum of absolute steps is more than 1.8x the net range, data is likely incremental.
        is_likely_incremental = running_sum > 1.8 * abs(total_range) and len(shg_s) > 3
        self._check(
            not is_likely_incremental,
            "MICP_INCREMENTAL_COLUMN_DETECTED",
            f"Saturation series shows incremental (delta) pattern — "
            f"sum of |ΔSat| ({running_sum:.3f}) >> net range ({total_range:.3f}). "
            "The parser likely chose an 'Incremental Intrusion' column instead of "
            "'Cumulative Intrusion'. Re-check column selection.",
        )

        return self

    def validate_archie(self, x, y, model_type="RI") -> "PhysicsGuard":
        """
        Validation for Resistivity Index (RI) or Formation Factor (FF).
        RI vs Sw: Monotone non-increasing, RI(Sw=1)=1
        FF vs Phi: Monotone non-increasing, FF(Phi=1) should be low
        """
        x_a = np.asarray(x, dtype=float)
        y_a = np.asarray(y, dtype=float)
        idx = np.argsort(x_a)
        x_s, y_s = x_a[idx], y_a[idx]

        if model_type == "RI":
            # Sw increases -> RI should decrease
            n_viol = int(np.sum(np.diff(y_s) > 1e-4))
            self._check(n_viol == 0, "RI_MONOTONICITY", f"Resistivity Index increases at {n_viol} point(s) as saturation increases.")
            self._check(bool(np.all(y_s >= 1.0 - 1e-4)), "RI_RANGE", "Resistivity Index cannot be less than 1.0.")
            # RI(Sw=1) should be near 1.0
            if x_s[-1] > 0.99:
                self._check(y_s[-1] < 1.1, "RI_ENDPOINT", f"RI at Sw=1 is {y_s[-1]:.2f}, should be 1.0.", severity="MEDIUM")
        else: # FF
            # Phi increases -> FF should decrease
            n_viol = int(np.sum(np.diff(y_s) > 1e-4))
            self._check(n_viol == 0, "FF_MONOTONICITY", f"Formation Factor increases at {n_viol} point(s) as porosity increases.")
            self._check(bool(np.all(y_s >= 1.0 - 1e-4)), "FF_RANGE", "Formation Factor cannot be less than 1.0.")

        return self

    def validate_pc(self, sw, pc, cycle: str = "drainage") -> "PhysicsGuard":
        """Validation for general Capillary Pressure (Centrifuge/Porous Plate).

        cycle='drainage'   (default) — Pc must be positive; negative values flagged.
        cycle='imbibition' — Pc is legitimately ≤ 0; PC_RANGE check is skipped.
        """
        sw_a = np.asarray(sw, dtype=float)
        pc_a = np.asarray(pc, dtype=float)
        idx  = np.argsort(sw_a)
        sw_s, pc_s = sw_a[idx], pc_a[idx]

        # Sw increases → Pc should decrease (applies to both drainage and imbibition)
        n_viol = int(np.sum(np.diff(pc_s) > 1e-4))
        self._check(n_viol == 0, "PC_MONOTONICITY",
                    f"Capillary Pressure increases at {n_viol} point(s) as water saturation increases.")

        # Sign check — imbibition Pc is negative by convention; skip for that cycle
        if cycle.lower() != "imbibition":
            self._check(bool(np.all(pc_s >= -0.1)), "PC_RANGE",
                        f"Capillary Pressure must be positive (found min={pc_s.min():.2f}).")

        return self

    def validate_archie_parameters(self, a: float, m: float, b: float, n: float) -> "PhysicsGuard":
        """
        Validate fitted Archie equation scalar parameters against physical bounds.

        Archie equations:
          FF = a · φ^-m   (Formation Factor)
          RI = b · Sw^-n  (Resistivity Index)

        Physical bounds for typical reservoir rock:
          a ∈ [0.5, 1.5]  — tortuosity factor
          m ∈ [1.3, 2.5]  — cementation exponent
          b ∈ [0.5, 1.5]  — saturation coefficient (standard form: b ≈ 1.0)
          n ∈ [1.5, 2.5]  — saturation exponent

        All four checks are HIGH severity: out-of-range parameters are
        impossible fits, not soft warnings.
        """
        self._check(
            0.5 <= float(a) <= 1.5,
            "ARCHIE_A_RANGE",
            f"Tortuosity factor a = {a:.4f} outside physical bounds [0.5, 1.5]. "
            "Values far from 1.0 suggest a poor fit or non-standard rock fabric.",
        )
        self._check(
            1.3 <= float(m) <= 2.5,
            "ARCHIE_M_RANGE",
            f"Cementation exponent m = {m:.4f} outside physical bounds [1.3, 2.5]. "
            "m < 1.3 is sub-physical; m > 2.5 requires independent lithological justification.",
        )
        self._check(
            0.5 <= float(b) <= 1.5,
            "ARCHIE_B_RANGE",
            f"Saturation coefficient b = {b:.4f} outside physical bounds [0.5, 1.5]. "
            "Standard Archie has b = 1.0; large deviation indicates fit instability.",
        )
        self._check(
            1.5 <= float(n) <= 2.5,
            "ARCHIE_N_RANGE",
            f"Saturation exponent n = {n:.4f} outside physical bounds [1.5, 2.5]. "
            "n < 1.5 is below observed rock range; n > 2.5 may indicate wettability alteration.",
        )
        return self

    # ── score generation ──────────────────────────────────────────────────────

    def generate_health_score(self) -> dict:
        """
        Returns a structured physics audit dict ready for JSON injection.

        Keys:
          score          – integer 0–100
          grade          – A/B/C/F
          icon           – ✅ / ⚠️ / 🚫
          violations     – list of {rule, severity, detail}
          rules_checked  – total rules evaluated
          summary        – one-line plain-English verdict
          footer         – formatted footer string for the UI
        """
        deduction = sum(
            self._HIGH_DEDUCTION   if v["severity"] == "HIGH"   else
            self._MEDIUM_DEDUCTION if v["severity"] == "MEDIUM" else 0
            for v in self._violations
        )
        score = max(0, 100 - deduction)

        if score >= 95:
            grade, icon = "A", "✅"
            summary = "All curves follow standard reservoir engineering monotonicity requirements."
        elif score >= 80:
            grade, icon = "B", "⚠️"
            n = len(self._violations)
            summary = (f"{n} minor physical inconsistenc{'y' if n == 1 else 'ies'} detected — "
                       "review before simulator submission.")
        elif score >= 60:
            grade, icon = "C", "⚠️"
            n = len(self._violations)
            summary = (f"{n} physical inconsistenc{'y' if n == 1 else 'ies'} detected — "
                       "data quality is marginal. Re-measurement recommended.")
        else:
            grade, icon = "F", "🚫"
            n = len(self._violations)
            summary = (f"CRITICAL: {n} violation(s) — data MUST NOT enter the "
                       "reservoir simulator without correction.")

        return {
            "score":         score,
            "grade":         grade,
            "icon":          icon,
            "violations":    self._violations,
            "rules_checked": self._rules_checked,
            "summary":       summary,
            "footer":        f"{icon} Physics Health Score: {score}%  |  Audit Result: {summary}",
        }


# ── LEGACY VALIDATOR ──────────────────────────────────────────────────────────

class PhysicsValidator:
    """
    Deterministic logic gate protecting the algorithms from AI hallucinations.
    """
    
    @staticmethod
    def format_precision(value: float, decimals: int = 4) -> float:
        return round(float(value), decimals)

    @staticmethod
    def validate_core_physics(data: dict) -> dict:
        swi = PhysicsValidator.format_precision(data.get('Swi', 0.0))
        sor = PhysicsValidator.format_precision(data.get('Sor', 0.0))
        porosity = PhysicsValidator.format_precision(data.get('Porosity', 0.0))
        
        if swi + sor > 1.0:
            raise PhysicsEngineError(
                f"PHYSICS VIOLATION: Swi ({swi}) + Sor ({sor}) = {swi + sor}. "
                "Total fluid saturation cannot mathematically exceed 1.0."
            )
            
        if porosity >= 1.0 or porosity <= 0.0:
            raise PhysicsEngineError(
                f"PHYSICS VIOLATION: Porosity ({porosity}) must be a fractional value between 0.0001 and 0.9999."
            )
            
        return {k: PhysicsValidator.format_precision(v) for k, v in data.items()}
