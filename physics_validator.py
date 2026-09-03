import logging

import numpy as np

_logger = logging.getLogger("prc-physics-guard")


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
    # "Nothing was validated" is not a deduction on a scale — it zeroes the score.
    _CRITICAL_DEDUCTION = 100

    # Hardcoded Archie windows. The single source for the sandbox corrector and
    # the validator: both resolve bounds through archie_bounds() so a "corrected"
    # fit can never be clamped to one window and judged against another.
    ARCHIE_BOUNDS_DEFAULT = {
        "a": (0.5, 1.5), "m": (1.3, 2.5), "b": (0.5, 1.5), "n": (1.5, 2.5),
    }

    def __init__(self):
        self._violations: list[dict]  = []
        self._rules_checked: int      = 0
        self._bounds_source: str | None = None

    @classmethod
    def archie_bounds(cls, basin_name: str = "Default") -> tuple[dict, str]:
        """Resolve Archie parameter windows: basin_physics_rules from the app DB
        when reachable, else the hardcoded defaults. Returns ``(bounds, source)``
        where source names what actually applied — the caller records it."""
        bounds = dict(cls.ARCHIE_BOUNDS_DEFAULT)
        basin = basin_name or "Default"
        try:
            from app import db
            rows = db("SELECT rule_key, min_limit, max_limit FROM basin_physics_rules WHERE basin_name=?", (basin,))
            if not rows and basin != "Default":
                rows = db("SELECT rule_key, min_limit, max_limit FROM basin_physics_rules WHERE basin_name='Default'")
                basin = "Default"
            for r_key, r_min, r_max in rows or []:
                if r_key in bounds:
                    bounds[r_key] = (float(r_min), float(r_max))
            return bounds, (f"db:basin_physics_rules[{basin}]" if rows else "hardcoded (no basin rules in db)")
        except Exception as exc:
            _logger.warning("[PhysicsGuard] basin rule fetch failed, hardcoded bounds apply: %s: %s",
                            type(exc).__name__, exc)
            return bounds, f"hardcoded (db unavailable: {type(exc).__name__})"

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

        # 4.5 — Check if saturation column has near-zero variance / is constant
        sat_range = float(np.max(shg_s) - np.min(shg_s))
        self._check(
            sat_range > 1e-4,
            "MICP_CONSTANT_SATURATION",
            f"Mercury saturation column has near-zero variance (range={sat_range:.6f}) — "
            "saturation must vary with pressure. This column is likely constant noise/junk.",
            severity="HIGH"
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
        Validate a measured Archie dataset (arrays, not fitted scalars).

          RI model: y = RI vs x = Sw  → RI = b·Sw^-n  (RI falls as Sw rises; RI ≥ 1)
          FF model: y = FF vs x = φ   → FF = a·φ^-m   (FF falls as φ rises; FF ≥ 1)

        Rules (HIGH unless noted):
          RI: RI_MONOTONICITY, RI_RANGE (≥1), RI_ENDPOINT (RI(Sw=1)≈1, MEDIUM)
          FF: FF_MONOTONICITY, FF_RANGE (≥1)
        """
        x_a = np.asarray(x, dtype=float)
        y_a = np.asarray(y, dtype=float)
        mt  = (model_type or "RI").upper()
        if x_a.size == 0 or y_a.size == 0:
            self._check(False, f"{mt}_NO_DATA",
                        f"{mt} dataset is empty — no rule was evaluated; this is not a pass.",
                        severity="CRITICAL")
            return self

        idx = np.argsort(x_a)
        y_s = y_a[idx]

        if mt == "FF":
            n_viol = int(np.sum(np.diff(y_s) > 1e-4))
            self._check(
                n_viol == 0,
                "FF_MONOTONICITY",
                f"Formation Factor increases at {n_viol} point(s) as porosity increases — "
                "violates FF = a·φ^-m (FF must fall as φ rises).",
            )
            self._check(
                bool(np.all(y_s >= 1.0 - 1e-6)),
                "FF_RANGE",
                f"Formation Factor below 1.0 (min={float(y_s.min()):.4f}) — non-physical; "
                "FF = R0/Rw ≥ 1 for any porosity < 1.",
            )
        else:  # RI
            n_viol = int(np.sum(np.diff(y_s) > 1e-4))
            self._check(
                n_viol == 0,
                "RI_MONOTONICITY",
                f"Resistivity Index increases at {n_viol} point(s) as Sw increases — "
                "violates RI = b·Sw^-n (RI must fall as Sw rises).",
            )
            self._check(
                bool(np.all(y_s >= 1.0 - 1e-6)),
                "RI_RANGE",
                f"Resistivity Index below 1.0 (min={float(y_s.min()):.4f}) — non-physical; "
                "RI = Rt/R0 ≥ 1 for Sw ≤ 1.",
            )
            ri_end = float(y_s[-1])  # RI at the highest Sw
            self._check(
                ri_end <= 1.1,
                "RI_ENDPOINT",
                f"RI at maximum Sw = {ri_end:.4f} exceeds 1.1 — RI must normalize to "
                "1.0 at full brine saturation (Sw = 1).",
                severity="MEDIUM",
            )
        return self

    def validate_pc(self, sw, pc, cycle: str = "drainage") -> "PhysicsGuard":
        """
        Validate a capillary pressure curve.

          PC_MONOTONICITY — Pc must be non-increasing as Sw increases (both cycles).
          PC_RANGE        — drainage Pc must be ≥ 0; negative Pc is non-physical in
                            drainage. For imbibition, negative Pc is correct and NOT flagged.
        """
        sw_a = np.asarray(sw, dtype=float)
        pc_a = np.asarray(pc, dtype=float)
        if sw_a.size == 0 or pc_a.size == 0:
            self._check(False, "PC_NO_DATA",
                        "Capillary pressure dataset is empty — no rule was evaluated; this is not a pass.",
                        severity="CRITICAL")
            return self

        idx  = np.argsort(sw_a)
        pc_s = pc_a[idx]

        n_viol = int(np.sum(np.diff(pc_s) > 1e-4))
        self._check(
            n_viol == 0,
            "PC_MONOTONICITY",
            f"Capillary pressure increases at {n_viol} point(s) as Sw increases — "
            "Pc must fall monotonically along the saturation axis.",
        )

        if str(cycle).lower() == "drainage":
            self._check(
                bool(np.all(pc_s >= -1e-6)),
                "PC_RANGE",
                f"Drainage capillary pressure goes negative (min={float(pc_s.min()):.4f}) — "
                "non-physical; drainage Pc ≥ 0 (negative Pc only occurs in imbibition).",
            )
        return self

    def validate_archie_parameters(self, a=None, m=None, b=None, n=None,
                                   basin_name: str = "Default",
                                   bounds: dict | None = None) -> "PhysicsGuard":
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

        Only the parameters actually passed are checked (``None`` = not fitted,
        not counted): a pair the caller never fitted must not add vacuous passes
        to rules_checked. All checks are HIGH severity: out-of-range parameters
        are impossible fits, not soft warnings. ``bounds`` injects the windows
        (the sandbox passes the ones it clamped to); otherwise they resolve via
        archie_bounds(). The window that applied is reported as
        ``bounds_source`` in the health block.
        """
        if bounds is None:
            bounds, self._bounds_source = self.archie_bounds(basin_name)
        else:
            self._bounds_source = "injected"
        if all(v is None for v in (a, m, b, n)):
            self._check(False, "ARCHIE_NO_PARAMETERS",
                        "No Archie parameter was supplied — nothing was validated.",
                        severity="CRITICAL")
            return self

        a_min, a_max = bounds["a"]
        m_min, m_max = bounds["m"]
        b_min, b_max = bounds["b"]
        n_min, n_max = bounds["n"]

        if a is not None:
            self._check(
                a_min <= float(a) <= a_max,
                "ARCHIE_A_RANGE",
                f"Tortuosity factor a = {a:.4f} outside physical bounds [{a_min}, {a_max}]. "
                "Values far from 1.0 suggest a poor fit or non-standard rock fabric.",
            )
        if m is not None:
            self._check(
                m_min <= float(m) <= m_max,
                "ARCHIE_M_RANGE",
                f"Cementation exponent m = {m:.4f} outside physical bounds [{m_min}, {m_max}]. "
                "m < 1.3 is sub-physical; m > 2.5 requires independent lithological justification.",
            )
        if b is not None:
            self._check(
                b_min <= float(b) <= b_max,
                "ARCHIE_B_RANGE",
                f"Saturation coefficient b = {b:.4f} outside physical bounds [{b_min}, {b_max}]. "
                "Standard Archie has b = 1.0; large deviation indicates fit instability.",
            )
        if n is not None:
            self._check(
                n_min <= float(n) <= n_max,
                "ARCHIE_N_RANGE",
                f"Saturation exponent n = {n:.4f} outside physical bounds [{n_min}, {n_max}]. "
                "n < 1.5 is below observed rock range; n > 2.5 may indicate wettability alteration.",
            )
        return self

    def validate_j_function(self, j_arr, sw_arr=None, ift_cos_theta: float = 26.5,
                            fluid_system: str = "Air-Mercury") -> "PhysicsGuard":
        """
        Validates Leverett J-Function values against physical domain boundaries.

        Physical bounds:
          - J at entry pressure should be < 0.5 for a correctly matched IFT.
            J > 0.5 at entry usually means the wrong σ·cos(θ) was used.
          - J > 2.0 at ANY saturation is physically impossible for consolidated rock.
          - J must be non-negative (negative Pc in drainage is non-physical).

        This catches the classic IFT mismatch hallucination (e.g., J = 1.272
        when the AI used air-mercury IFT of 26.5 dyn/cm for an air-brine system
        that should use ~72 dyn/cm).
        """
        j_a = np.asarray(j_arr, dtype=float)

        # 1 — J must be non-negative (drainage cycle)
        n_neg = int(np.sum(j_a < -1e-6))
        self._check(
            n_neg == 0,
            "J_NEGATIVE",
            f"{n_neg} J-Function value(s) are negative — non-physical for "
            "drainage capillary pressure.",
        )

        # 2 — J at entry pressure (first J where Sw < 0.95)
        if sw_arr is not None:
            sw_a = np.asarray(sw_arr, dtype=float)
            entry_mask = sw_a < 0.95
            if entry_mask.any():
                j_entry = float(j_a[entry_mask][0])
                self._check(
                    j_entry <= 0.5,
                    "J_ENTRY_IFT_MISMATCH",
                    f"Critical Physics Violation: J-Function at entry = {j_entry:.4f} "
                    f"(should be < 0.5). This usually means the wrong Interfacial "
                    f"Tension (IFT) was used for the {fluid_system} system. "
                    f"Current σ·cos(θ) = {ift_cos_theta} dyn/cm — verify against "
                    f"the actual fluid pair.",
                )

        # 3 — Maximum J cannot exceed 2.0 for consolidated reservoir rock
        j_max = float(j_a.max())
        self._check(
            j_max <= 2.0,
            "J_MAX_IMPOSSIBLE",
            f"J-Function max = {j_max:.4f} exceeds 2.0 — physically impossible "
            "for consolidated reservoir rock. Check IFT, permeability, or porosity inputs.",
        )

        # 4 — J > 5.0 is absolutely impossible under any conditions
        self._check(
            j_max <= 5.0,
            "J_CATASTROPHIC",
            f"CATASTROPHIC: J-Function max = {j_max:.4f}. Values > 5.0 indicate "
            "a unit conversion error or completely wrong input parameters.",
        )

        return self

    def validate_compressibility(self, cp_values, pressures=None) -> "PhysicsGuard":
        """
        Validates Pore Volume Compressibility (Cp) against physical domain boundaries.

        Physical bounds (psi⁻¹):
          - Cp must be non-negative (pore volume cannot expand under compression).
          - Cp < 3.0e-6:  Tight carbonate / cemented sandstone (normal).
          - Cp 3–10e-6:   Typical consolidated sandstone.
          - Cp 10–30e-6:  Unconsolidated / friable sand (plausible).
          - Cp 30–50e-6:  Very weak chalk, diatomite (rare but physical).
          - Cp > 50e-6:   Physically implausible — likely a calculation error.
        """
        cp_a = np.asarray(cp_values, dtype=float)
        # Filter out null/zero baseline values
        cp_valid = cp_a[np.isfinite(cp_a) & (cp_a != 0.0)]

        if len(cp_valid) == 0:
            self._check(False, "CP_NO_DATA",
                        f"No finite non-zero Cp value among {cp_a.size} input(s) — no rule was "
                        "evaluated; this is not a pass.",
                        severity="CRITICAL")
            return self

        # 1 — Cp must be non-negative
        n_neg = int(np.sum(cp_valid < -1e-10))
        self._check(
            n_neg == 0,
            "CP_NEGATIVE",
            f"{n_neg} Cp value(s) are negative — pore volume cannot expand "
            "under increasing confining pressure (check calculation sign).",
        )

        # 2 — Cp cannot exceed 50e-6 psi⁻¹ (even for unconsolidated chalk)
        cp_max = float(cp_valid.max())
        self._check(
            cp_max <= 50.0e-6,
            "CP_MAX_IMPOSSIBLE",
            f"Cp max = {cp_max:.2e} psi⁻¹ exceeds 50×10⁻⁶ — physically "
            "implausible. Only unconsolidated chalk/diatomite reaches 30–50×10⁻⁶. "
            "Check porosity units or pressure delta calculation.",
        )

        # 3 — Cp > 100e-6 is a catastrophic calculation error
        self._check(
            cp_max <= 100.0e-6,
            "CP_CATASTROPHIC",
            f"CATASTROPHIC: Cp max = {cp_max:.2e} psi⁻¹ — this exceeds any "
            "known reservoir rock. Likely a unit error (porosity in fraction vs percent?).",
        )

        return self

    def validate_saturation_endpoints(self, swi: float, sor: float,
                                       sample: str = "") -> "PhysicsGuard":
        """
        Validates Swi (irreducible water saturation) and Sor (residual oil saturation)
        endpoint values for physical consistency.

        Physical bounds:
          - Swi + Sor must be < 1.0 (mass conservation: there must be mobile fluid).
          - Swi typically 0.05–0.60 for reservoir rock.
          - Sor typically 0.05–0.45 for waterflooded sandstone.
          - Swi > 0.80 or Sor > 0.50 are extreme outliers requiring justification.
        """
        prefix = f"[{sample}] " if sample else ""

        # 1 — Mass conservation: Swi + Sor < 1.0
        total = float(swi) + float(sor)
        self._check(
            total < 1.0,
            "SAT_MASS_CONSERVATION",
            f"{prefix}Swi ({swi:.4f}) + Sor ({sor:.4f}) = {total:.4f} ≥ 1.0 — "
            "violates mass conservation. No mobile fluid phase exists.",
        )

        # 2 — Swi plausibility
        self._check(
            0.0 <= float(swi) <= 0.80,
            "SWI_RANGE",
            f"{prefix}Swi = {swi:.4f} outside plausible range [0, 0.80]. "
            "Swi > 0.80 means >80% of pore space is immobile water — "
            "extremely rare, verify lab data.",
            severity="MEDIUM",
        )

        # 3 — Sor plausibility
        self._check(
            0.0 <= float(sor) <= 0.50,
            "SOR_RANGE",
            f"{prefix}Sor = {sor:.4f} outside plausible range [0, 0.50]. "
            "Sor > 0.50 means >50% of pore space is trapped oil — "
            "verify wettability and flood efficiency.",
            severity="MEDIUM",
        )

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
            self._CRITICAL_DEDUCTION if v["severity"] == "CRITICAL" else
            self._HIGH_DEDUCTION   if v["severity"] == "HIGH"   else
            self._MEDIUM_DEDUCTION if v["severity"] == "MEDIUM" else 0
            for v in self._violations
        )
        score = max(0, 100 - deduction)

        if self._rules_checked == 0:
            # No rule ran: an A here would be a signal that cannot be false. The
            # numeric score stays undeducted (pinned by test_fresh_guard_starts_empty);
            # grade / summary / footer carry the verdict.
            grade, icon = "N/A", "❔"
            summary = "No physics rule was evaluated — nothing has been validated."
        elif score >= 95:
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
            "bounds_source": self._bounds_source,
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
        missing = [k for k in ('Swi', 'Sor', 'Porosity') if data.get(k) is None]
        if missing:
            # A defaulted 0.0 endpoint passes the mass check for a value nobody supplied.
            raise PhysicsEngineError(
                f"PHYSICS VALIDATION IMPOSSIBLE: missing {', '.join(missing)} — "
                "endpoints cannot be defaulted to 0.0 and then declared consistent."
            )
        swi = PhysicsValidator.format_precision(data['Swi'])
        sor = PhysicsValidator.format_precision(data['Sor'])
        porosity = PhysicsValidator.format_precision(data['Porosity'])
        
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
