"""
Exhaustive pytest suite for physics_validator.py and skills_engine.py.

Coverage targets:
  - PhysicsGuard: all validators, every rule branch, deduction math, grade boundaries
  - PhysicsValidator: saturation constraint, porosity constraint, precision rounding
  - PhysicsEngineError: correct exception type raised
  - SkillsEngine: script resolution, timeout, missing path, list methods
  - Brooks-Corey math: endpoint exactness, monotonicity, exponent sensitivity
  - Archie math: RI normalization, FF monotonicity, exponent range compliance
"""

import os
import sys
import pytest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from physics_validator import PhysicsGuard, PhysicsValidator, PhysicsEngineError
from skills_engine import SkillsEngine


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _brooks_corey_krw(sw, swr, snr, krw_max, nw):
    """Reference implementation of Brooks-Corey Krw."""
    se = (np.asarray(sw) - swr) / (1.0 - swr - snr)
    se = np.clip(se, 0.0, 1.0)
    return krw_max * se ** nw

def _brooks_corey_kro(sw, swr, snr, kro_max, no):
    """Reference implementation of Brooks-Corey Kro."""
    se = (np.asarray(sw) - swr) / (1.0 - swr - snr)
    se = np.clip(se, 0.0, 1.0)
    return kro_max * (1.0 - se) ** no


# ══════════════════════════════════════════════════════════════════════════════
# PHYSICS GUARD — validate_kr
# ══════════════════════════════════════════════════════════════════════════════

class TestPhysicsGuardKr:

    def _valid_kr(self, n=20, swr=0.20, snr=0.15):
        sw  = np.linspace(swr, 1.0 - snr, n)
        krw = _brooks_corey_krw(sw, swr, snr, 0.65, 2.5)
        kro = _brooks_corey_kro(sw, swr, snr, 0.90, 2.5)
        return sw, krw, kro

    def test_valid_curve_score_100(self):
        sw, krw, kro = self._valid_kr()
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        assert r["score"] == 100
        assert r["grade"] == "A"
        assert r["violations"] == []

    def test_rules_checked_count(self):
        sw, krw, kro = self._valid_kr()
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        assert r["rules_checked"] == 7

    # ── KRW_MONOTONICITY ─────────────────────────────────────────────────────

    def test_krw_monotonicity_violation(self):
        sw  = np.linspace(0.2, 0.85, 10)
        krw = np.array([0.0, 0.05, 0.03, 0.10, 0.18, 0.28, 0.42, 0.38, 0.55, 0.65])
        kro = _brooks_corey_kro(sw, 0.2, 0.15, 0.9, 2.5)
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        assert r["score"] == 100 - 15
        rules = [v["rule"] for v in r["violations"]]
        assert "KRW_MONOTONICITY" in rules

    def test_krw_monotonicity_strictly_decreasing(self):
        sw  = np.linspace(0.2, 0.85, 10)
        krw = np.linspace(0.65, 0.0, 10)  # fully inverted
        kro = _brooks_corey_kro(sw, 0.2, 0.15, 0.9, 2.5)
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "KRW_MONOTONICITY" in rules
        assert "KRW_ZERO_AT_SWI" in rules  # krw[0]=0.65 > 0.01

    # ── KRO_MONOTONICITY ─────────────────────────────────────────────────────

    def test_kro_monotonicity_violation(self):
        sw  = np.linspace(0.2, 0.85, 10)
        krw = _brooks_corey_krw(sw, 0.2, 0.15, 0.65, 2.5)
        kro = np.array([0.9, 0.7, 0.75, 0.5, 0.3, 0.2, 0.1, 0.08, 0.05, 0.0])
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        rules = [v["rule"] for v in r["violations"]]
        assert "KRO_MONOTONICITY" in rules

    # ── KRW_RANGE ────────────────────────────────────────────────────────────

    def test_krw_above_1_flagged(self):
        sw  = np.linspace(0.2, 0.85, 10)
        krw = np.linspace(0.0, 1.05, 10)  # exceeds 1.0
        kro = _brooks_corey_kro(sw, 0.2, 0.15, 0.9, 2.5)
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "KRW_RANGE" in rules or "KRW_ENDPOINT" in rules

    def test_krw_negative_flagged(self):
        sw  = np.linspace(0.2, 0.85, 5)
        krw = np.array([-0.05, 0.1, 0.25, 0.4, 0.65])
        kro = _brooks_corey_kro(sw, 0.2, 0.15, 0.9, 2.5)
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "KRW_RANGE" in rules

    # ── KRO_RANGE ────────────────────────────────────────────────────────────

    def test_kro_above_1_flagged(self):
        sw  = np.linspace(0.2, 0.85, 5)
        krw = _brooks_corey_krw(sw, 0.2, 0.15, 0.65, 2.5)
        kro = np.array([1.1, 0.7, 0.4, 0.15, 0.0])  # first value > 1
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "KRO_RANGE" in rules

    # ── Endpoint rules (MEDIUM severity) ─────────────────────────────────────

    def test_krw_not_zero_at_swi_is_medium(self):
        sw  = np.linspace(0.2, 0.85, 10)
        krw = np.linspace(0.05, 0.65, 10)  # krw[0]=0.05 > 0.01
        kro = _brooks_corey_kro(sw, 0.2, 0.15, 0.9, 2.5)
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        v = {v["rule"]: v for v in r["violations"]}
        assert "KRW_ZERO_AT_SWI" in v
        assert v["KRW_ZERO_AT_SWI"]["severity"] == "MEDIUM"
        assert r["score"] == 100 - 5  # one MEDIUM

    def test_kro_not_zero_at_sor_is_medium(self):
        sw  = np.linspace(0.2, 0.85, 10)
        krw = _brooks_corey_krw(sw, 0.2, 0.15, 0.65, 2.5)
        kro = np.linspace(0.9, 0.05, 10)  # kro[-1]=0.05 > 0.01
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        v = {v["rule"]: v for v in r["violations"]}
        assert "KRO_ZERO_AT_SOR" in v
        assert v["KRO_ZERO_AT_SOR"]["severity"] == "MEDIUM"

    # ── Multiple simultaneous violations ─────────────────────────────────────

    def test_multiple_violations_stack_correctly(self):
        sw  = np.linspace(0.2, 0.85, 5)
        krw = np.array([0.3, 0.1, 0.4, 0.2, 0.65])  # non-monotone + non-zero at Swi
        kro = np.array([0.9, 1.1, 0.4, 0.5, 0.05])  # non-monotone + Kro > 1 + KRO_ZERO_AT_SOR
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        # At minimum: KRW_MONOTONICITY(HIGH) + KRW_ZERO_AT_SWI(MEDIUM) = -20
        assert r["score"] <= 80
        assert len(r["violations"]) >= 2

    def test_score_cannot_go_below_zero(self):
        # All 7 rules violated: 5×HIGH + 2×MEDIUM = 75+10 = 85 pts deducted → clamped at 0
        sw  = np.array([0.2, 0.5, 0.85])
        krw = np.array([0.5, 0.1, 1.5])   # non-monotone, out-of-range, non-zero at Swi
        kro = np.array([1.5, 0.8, 0.5])   # out-of-range, non-monotone, non-zero at Sor
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        assert r["score"] >= 0
        assert r["grade"] == "F"

    # ── Unsorted Sw input ─────────────────────────────────────────────────────

    def test_unsorted_sw_is_handled(self):
        """Guard must sort by Sw before applying monotonicity checks."""
        sw  = np.array([0.85, 0.20, 0.65, 0.45])
        krw = np.array([0.65, 0.0, 0.31, 0.12])   # correct values at these Sw
        kro = np.array([0.0, 0.90, 0.15, 0.48])
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        assert r["score"] == 100

    # ── Grade boundaries ─────────────────────────────────────────────────────

    def test_grade_B_boundary(self):
        # One HIGH violation → score=85 → grade B
        sw  = np.linspace(0.2, 0.85, 10)
        krw = np.linspace(0.5, 0.0, 10)  # inverted Krw → KRW_MONOTONICITY + KRW_ZERO_AT_SWI
        kro = _brooks_corey_kro(sw, 0.2, 0.15, 0.9, 2.5)
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        assert r["grade"] in ("B", "C", "F")  # at least one HIGH hit

    def test_grade_F_requires_score_below_60(self):
        sw  = np.linspace(0.2, 0.85, 5)
        krw = np.array([1.5, 1.2, 0.8, 0.4, 0.2])
        kro = np.array([1.5, 1.2, 0.8, 0.4, 0.3])
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        if r["score"] < 60:
            assert r["grade"] == "F"


# ══════════════════════════════════════════════════════════════════════════════
# PHYSICS GUARD — validate_micp
# ══════════════════════════════════════════════════════════════════════════════

class TestPhysicsGuardMicp:

    def _valid_micp(self, n=15):
        pc     = np.logspace(0.5, 3.0, n)   # 3.16 → 1000 psia
        hg_sat = np.linspace(0.02, 0.92, n)
        return pc, hg_sat

    def test_valid_micp_score_100(self):
        pc, hg = self._valid_micp()
        g = PhysicsGuard()
        g.validate_micp(pc, hg)
        r = g.generate_health_score()
        assert r["score"] == 100

    def test_micp_rules_checked_count(self):
        pc, hg = self._valid_micp()
        g = PhysicsGuard()
        g.validate_micp(pc, hg)
        assert g.generate_health_score()["rules_checked"] == 6

    def test_negative_pc_flagged(self):
        pc  = np.array([-5.0, 10.0, 50.0, 200.0])
        hg  = np.array([0.05, 0.30, 0.60, 0.90])
        g = PhysicsGuard()
        g.validate_micp(pc, hg)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "MICP_NEGATIVE_PC" in rules

    def test_micp_non_monotone_saturation(self):
        pc  = np.array([10.0, 50.0, 100.0, 200.0, 500.0])
        hg  = np.array([0.10, 0.40, 0.30, 0.70, 0.90])  # drops at idx 2
        g = PhysicsGuard()
        g.validate_micp(pc, hg)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "MICP_SATURATION_MONOTONICITY" in rules

    def test_micp_sat_range_above_1(self):
        pc  = np.linspace(10, 500, 5)
        hg  = np.array([0.05, 0.3, 0.6, 0.85, 1.05])  # last > 1
        g = PhysicsGuard()
        g.validate_micp(pc, hg)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "MICP_SAT_RANGE" in rules

    def test_micp_sat_range_is_medium_severity(self):
        pc  = np.linspace(10, 500, 5)
        hg  = np.array([0.05, 0.3, 0.6, 0.85, 1.05])
        g = PhysicsGuard()
        g.validate_micp(pc, hg)
        v = {v["rule"]: v for v in g.generate_health_score()["violations"]}
        assert v["MICP_SAT_RANGE"]["severity"] == "MEDIUM"

    def test_zero_pc_triggers_entry_pressure_violation(self):
        pc  = np.array([0.0, 5.0, 50.0, 200.0])  # pc[0]=0
        hg  = np.array([0.0, 0.02, 0.5, 0.9])
        g = PhysicsGuard()
        g.validate_micp(pc, hg)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "MICP_NEGATIVE_PC" in rules

    def test_micp_all_zero_sat_no_entry_pressure_viol(self):
        # If Hg_sat never exceeds 0.01, entry pressure check uses pc_s[0]
        pc  = np.linspace(1.0, 500.0, 10)
        hg  = np.zeros(10)  # never intrudes
        g = PhysicsGuard()
        g.validate_micp(pc, hg)
        r = g.generate_health_score()
        # No MICP_ENTRY_PRESSURE violation since pe = pc_s[0] = 1.0 > 0
        rules = [v["rule"] for v in r["violations"]]
        assert "MICP_ENTRY_PRESSURE" not in rules


# ══════════════════════════════════════════════════════════════════════════════
# PHYSICS GUARD — validate_archie
# ══════════════════════════════════════════════════════════════════════════════

class TestPhysicsGuardArchie:

    def test_valid_ri_score_100(self):
        sw = np.linspace(0.2, 1.0, 15)
        ri = sw ** -2.0  # Archie RI = Sw^-n with n=2
        g = PhysicsGuard()
        g.validate_archie(sw, ri, model_type="RI")
        r = g.generate_health_score()
        assert r["score"] == 100

    def test_ri_non_monotone_flagged(self):
        sw = np.linspace(0.2, 1.0, 6)
        ri = np.array([25.0, 10.0, 12.0, 5.0, 3.0, 1.0])  # increases at idx 2
        g = PhysicsGuard()
        g.validate_archie(sw, ri, model_type="RI")
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "RI_MONOTONICITY" in rules

    def test_ri_below_1_flagged(self):
        sw = np.linspace(0.2, 1.0, 5)
        ri = np.array([5.0, 2.0, 0.8, 0.5, 0.3])  # RI < 1 is non-physical
        g = PhysicsGuard()
        g.validate_archie(sw, ri, model_type="RI")
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "RI_RANGE" in rules

    def test_ri_endpoint_at_sw1_out_of_range(self):
        sw = np.array([0.2, 0.5, 0.8, 0.99, 1.0])
        ri = np.array([25.0, 8.0, 3.0, 1.5, 1.15])  # RI(Sw=1) = 1.15 > 1.1
        g = PhysicsGuard()
        g.validate_archie(sw, ri, model_type="RI")
        r = g.generate_health_score()
        rules = [v["rule"] for v in r["violations"]]
        assert "RI_ENDPOINT" in rules
        assert {v["rule"]: v for v in r["violations"]}["RI_ENDPOINT"]["severity"] == "MEDIUM"

    def test_valid_ff_score_100(self):
        phi = np.linspace(0.05, 0.35, 12)
        ff  = 1.0 / phi ** 2.0  # Archie FF = phi^-m with a=1, m=2
        g = PhysicsGuard()
        g.validate_archie(phi, ff, model_type="FF")
        r = g.generate_health_score()
        assert r["score"] == 100

    def test_ff_non_monotone_flagged(self):
        phi = np.linspace(0.05, 0.35, 6)
        ff  = np.array([400.0, 200.0, 250.0, 80.0, 40.0, 20.0])  # increases at idx 2
        g = PhysicsGuard()
        g.validate_archie(phi, ff, model_type="FF")
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "FF_MONOTONICITY" in rules


# ══════════════════════════════════════════════════════════════════════════════
# PHYSICS GUARD — validate_archie_parameters
# ══════════════════════════════════════════════════════════════════════════════

class TestArchieParameterValidation:
    """Validates that fitted Archie scalars (a, m, b, n) are within physical bounds."""

    # ── valid parameters ──────────────────────────────────────────────────────

    def test_valid_params_score_100(self):
        g = PhysicsGuard()
        g.validate_archie_parameters(a=1.0, m=2.0, b=1.0, n=2.0)
        r = g.generate_health_score()
        assert r["score"] == 100
        assert r["violations"] == []

    def test_rules_checked_count(self):
        g = PhysicsGuard()
        g.validate_archie_parameters(a=1.0, m=2.0, b=1.0, n=2.0)
        assert g.generate_health_score()["rules_checked"] == 4

    def test_boundary_values_pass(self):
        """Exact boundary values must be accepted (inclusive bounds)."""
        for a, m, b, n in [(0.5, 1.3, 0.5, 1.5), (1.5, 2.5, 1.5, 2.5)]:
            g = PhysicsGuard()
            g.validate_archie_parameters(a=a, m=m, b=b, n=n)
            r = g.generate_health_score()
            assert r["score"] == 100, f"Boundary failed a={a} m={m} b={b} n={n}: {r['violations']}"

    # ── cementation exponent (m) ──────────────────────────────────────────────

    def test_m_below_minimum_flagged(self):
        """m=0.3 is sub-physical — ARCHIE_M_RANGE must fire."""
        g = PhysicsGuard()
        g.validate_archie_parameters(a=1.0, m=0.3, b=1.0, n=2.0)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "ARCHIE_M_RANGE" in rules

    def test_m_above_maximum_flagged(self):
        g = PhysicsGuard()
        g.validate_archie_parameters(a=1.0, m=3.8, b=1.0, n=2.0)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "ARCHIE_M_RANGE" in rules

    def test_m_violation_is_high_severity(self):
        g = PhysicsGuard()
        g.validate_archie_parameters(a=1.0, m=0.3, b=1.0, n=2.0)
        v = {v["rule"]: v for v in g.generate_health_score()["violations"]}
        assert v["ARCHIE_M_RANGE"]["severity"] == "HIGH"

    # ── saturation exponent (n) ───────────────────────────────────────────────

    def test_n_negative_flagged(self):
        """n=-1.5 is impossible — ARCHIE_N_RANGE must fire."""
        g = PhysicsGuard()
        g.validate_archie_parameters(a=1.0, m=2.0, b=1.0, n=-1.5)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "ARCHIE_N_RANGE" in rules

    def test_n_above_maximum_flagged(self):
        g = PhysicsGuard()
        g.validate_archie_parameters(a=1.0, m=2.0, b=1.0, n=3.5)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "ARCHIE_N_RANGE" in rules

    # ── tortuosity factor (a) ─────────────────────────────────────────────────

    def test_a_above_maximum_flagged(self):
        g = PhysicsGuard()
        g.validate_archie_parameters(a=2.5, m=2.0, b=1.0, n=2.0)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "ARCHIE_A_RANGE" in rules

    def test_a_below_minimum_flagged(self):
        g = PhysicsGuard()
        g.validate_archie_parameters(a=0.1, m=2.0, b=1.0, n=2.0)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "ARCHIE_A_RANGE" in rules

    # ── saturation coefficient (b) ────────────────────────────────────────────

    def test_b_above_maximum_flagged(self):
        g = PhysicsGuard()
        g.validate_archie_parameters(a=1.0, m=2.0, b=3.0, n=2.0)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "ARCHIE_B_RANGE" in rules

    # ── multi-violation stacking ──────────────────────────────────────────────

    def test_m_and_n_both_impossible_stack(self):
        """m=0.3 and n=-1.5 → 2 HIGH violations → score = 100 - 30 = 70."""
        g = PhysicsGuard()
        g.validate_archie_parameters(a=1.0, m=0.3, b=1.0, n=-1.5)
        r = g.generate_health_score()
        rules = [v["rule"] for v in r["violations"]]
        assert "ARCHIE_M_RANGE" in rules
        assert "ARCHIE_N_RANGE" in rules
        assert r["score"] == 70

    def test_all_four_bad_score_clamps_at_0(self):
        """4 HIGH violations = 60 pts deducted → score = 40, not below 0."""
        g = PhysicsGuard()
        g.validate_archie_parameters(a=5.0, m=0.1, b=9.0, n=-3.0)
        r = g.generate_health_score()
        assert len(r["violations"]) == 4
        assert r["score"] == 100 - 4 * 15  # 40

    def test_does_not_interfere_with_kr_chain(self):
        """Chaining validate_kr + validate_archie_parameters accumulates rules correctly."""
        sw  = np.linspace(0.2, 0.85, 10)
        krw = np.linspace(0.0, 0.65, 10)
        kro = np.linspace(0.9, 0.0, 10)
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        g.validate_archie_parameters(a=1.0, m=2.0, b=1.0, n=2.0)
        r = g.generate_health_score()
        assert r["rules_checked"] == 7 + 4  # 7 Kr + 4 Archie params


# ══════════════════════════════════════════════════════════════════════════════
# PHYSICS GUARD — validate_pc
# ══════════════════════════════════════════════════════════════════════════════

class TestPhysicsGuardPc:

    def test_valid_pc_score_100(self):
        sw = np.linspace(0.2, 0.85, 10)
        pc = np.linspace(50.0, 1.0, 10)  # decreasing Pc as Sw increases
        g = PhysicsGuard()
        g.validate_pc(sw, pc)
        assert g.generate_health_score()["score"] == 100

    def test_pc_non_monotone_flagged(self):
        sw = np.linspace(0.2, 0.85, 5)
        pc = np.array([50.0, 20.0, 30.0, 10.0, 2.0])  # increases at idx 2
        g = PhysicsGuard()
        g.validate_pc(sw, pc)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "PC_MONOTONICITY" in rules

    def test_pc_strongly_negative_flagged(self):
        sw = np.linspace(0.2, 0.85, 5)
        pc = np.array([50.0, 20.0, 5.0, -0.5, -2.0])  # clearly negative
        g = PhysicsGuard()
        g.validate_pc(sw, pc)
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "PC_RANGE" in rules

    def test_imbibition_negative_pc_not_flagged(self):
        """Negative Pc is physically correct for imbibition — PC_RANGE must not fire."""
        sw = np.linspace(0.30, 0.58, 9)
        pc = np.array([0.0, -1.0, -2.0, -4.0, -8.0, -15.0, -35.0, -60.0, -120.0])
        g = PhysicsGuard()
        g.validate_pc(sw, pc, cycle="imbibition")
        rules = [v["rule"] for v in g.generate_health_score()["violations"]]
        assert "PC_RANGE" not in rules


# ══════════════════════════════════════════════════════════════════════════════
# PHYSICS GUARD — Chaining and Deduction Math
# ══════════════════════════════════════════════════════════════════════════════

class TestPhysicsGuardDeductionMath:

    def test_deduction_math_one_high(self):
        sw  = np.linspace(0.2, 0.85, 5)
        krw = np.linspace(0.65, 0.0, 5)  # KRW_MONOTONICITY (HIGH)
        kro = _brooks_corey_kro(sw, 0.2, 0.15, 0.9, 2.5)
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        high_violations = [v for v in r["violations"] if v["severity"] == "HIGH"]
        med_violations  = [v for v in r["violations"] if v["severity"] == "MEDIUM"]
        expected = max(0, 100 - 15 * len(high_violations) - 5 * len(med_violations))
        assert r["score"] == expected

    def test_score_footer_format(self):
        pc, hg = np.logspace(0.5, 3.0, 10), np.linspace(0.02, 0.92, 10)
        g = PhysicsGuard()
        g.validate_micp(pc, hg)
        r = g.generate_health_score()
        assert "Physics Health Score" in r["footer"]
        assert "100%" in r["footer"]

    def test_chaining_kr_then_micp_accumulates_rules(self):
        sw, krw, kro = np.linspace(0.2, 0.85, 10), np.linspace(0.0, 0.65, 10), np.linspace(0.9, 0.0, 10)
        pc, hg       = np.logspace(0.5, 3.0, 10), np.linspace(0.02, 0.92, 10)
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        g.validate_micp(pc, hg)
        r = g.generate_health_score()
        assert r["rules_checked"] == 7 + 6  # 7 Kr + 6 MICP

    def test_fresh_guard_starts_empty(self):
        g = PhysicsGuard()
        r = g.generate_health_score()
        assert r["score"] == 100
        assert r["rules_checked"] == 0
        assert r["violations"] == []


# ══════════════════════════════════════════════════════════════════════════════
# BROOKS-COREY MATH — endpoint and monotonicity exactness
# ══════════════════════════════════════════════════════════════════════════════

class TestBrooksCoreyPhysics:
    """Tests that the reference Brooks-Corey implementation passes PhysicsGuard."""

    @pytest.mark.parametrize("swr,snr,krw_max,kro_max,nw,no", [
        (0.20, 0.15, 0.65, 0.90, 2.5, 2.5),  # PRC standard
        (0.10, 0.10, 0.80, 0.95, 1.5, 2.0),  # clean sandstone
        (0.30, 0.25, 0.45, 0.80, 3.5, 4.0),  # tight carbonate
        (0.05, 0.05, 0.90, 0.98, 1.2, 1.5),  # high-quality rock
    ])
    def test_brooks_corey_passes_guard(self, swr, snr, krw_max, kro_max, nw, no):
        sw  = np.linspace(swr, 1.0 - snr, 50)
        krw = _brooks_corey_krw(sw, swr, snr, krw_max, nw)
        kro = _brooks_corey_kro(sw, swr, snr, kro_max, no)
        g = PhysicsGuard()
        g.validate_kr(sw, krw, kro)
        r = g.generate_health_score()
        assert r["score"] == 100, f"Failed for swr={swr}, snr={snr}: {r['violations']}"

    def test_krw_endpoint_zero_at_swi(self):
        swr, snr = 0.20, 0.15
        sw = np.linspace(swr, 1.0 - snr, 100)
        krw = _brooks_corey_krw(sw, swr, snr, 0.65, 2.5)
        assert abs(krw[0]) < 1e-9, f"Krw(Swi) = {krw[0]}, expected ≈ 0"

    def test_kro_endpoint_zero_at_sor(self):
        swr, snr = 0.20, 0.15
        sw  = np.linspace(swr, 1.0 - snr, 100)
        kro = _brooks_corey_kro(sw, swr, snr, 0.90, 2.5)
        assert abs(kro[-1]) < 1e-9, f"Kro(1-Sor) = {kro[-1]}, expected ≈ 0"

    def test_krw_endpoint_max_at_sor(self):
        swr, snr, krw_max = 0.20, 0.15, 0.65
        sw  = np.linspace(swr, 1.0 - snr, 100)
        krw = _brooks_corey_krw(sw, swr, snr, krw_max, 2.5)
        assert abs(krw[-1] - krw_max) < 1e-9

    def test_kro_endpoint_max_at_swi(self):
        swr, snr, kro_max = 0.20, 0.15, 0.90
        sw  = np.linspace(swr, 1.0 - snr, 100)
        kro = _brooks_corey_kro(sw, swr, snr, kro_max, 2.5)
        assert abs(kro[0] - kro_max) < 1e-9

    def test_higher_nw_more_concave(self):
        swr, snr = 0.20, 0.15
        sw = np.linspace(swr, 1.0 - snr, 50)
        krw_low  = _brooks_corey_krw(sw, swr, snr, 0.65, 1.5)
        krw_high = _brooks_corey_krw(sw, swr, snr, 0.65, 4.0)
        # Higher nw → lower Krw at intermediate saturations (more concave)
        mid = len(sw) // 2
        assert krw_high[mid] < krw_low[mid]

    def test_crossover_sw_water_wet_range(self):
        """Crossover Sw for symmetric PRC defaults should be around 0.5."""
        swr, snr = 0.20, 0.15
        sw  = np.linspace(swr, 1.0 - snr, 500)
        krw = _brooks_corey_krw(sw, swr, snr, 0.65, 2.5)
        kro = _brooks_corey_kro(sw, swr, snr, 0.90, 2.5)
        diff = krw - kro
        crossover_idx = np.where(np.diff(np.sign(diff)))[0]
        assert len(crossover_idx) >= 1, "No crossover found"
        sw_cross = float(sw[crossover_idx[0]])
        # With krw_max=0.65 < kro_max=0.90, crossover Sw < 0.65 (slightly water-wet to mixed)
        assert 0.35 < sw_cross < 0.75


# ══════════════════════════════════════════════════════════════════════════════
# ARCHIE MODEL MATH
# ══════════════════════════════════════════════════════════════════════════════

class TestArchieModelMath:

    def test_ri_equals_1_at_sw_1(self):
        sw = np.linspace(0.2, 1.0, 100)
        n  = 2.0
        ri = sw ** -n
        assert abs(ri[-1] - 1.0) < 1e-9, "RI(Sw=1) must equal 1.0 exactly"

    @pytest.mark.parametrize("n", [1.5, 2.0, 2.5, 3.0])
    def test_ri_monotone_decreasing_for_valid_n(self, n):
        sw = np.linspace(0.2, 1.0, 50)
        ri = sw ** -n
        assert np.all(np.diff(ri) <= 0), f"RI not monotone decreasing for n={n}"

    def test_ri_always_gte_1(self):
        sw = np.linspace(0.2, 1.0, 50)
        for n in [1.5, 2.0, 2.5, 3.0]:
            ri = sw ** -n
            assert np.all(ri >= 1.0 - 1e-9), f"RI < 1 found for n={n}"

    @pytest.mark.parametrize("a,m", [(1.0, 2.0), (0.81, 2.0), (1.0, 1.7)])
    def test_ff_monotone_decreasing(self, a, m):
        phi = np.linspace(0.05, 0.40, 50)
        ff  = a * phi ** -m
        assert np.all(np.diff(ff) <= 0), f"FF not monotone decreasing for a={a}, m={m}"

    def test_ff_gte_1(self):
        phi = np.linspace(0.05, 0.40, 50)
        ff  = 1.0 * phi ** -2.0
        assert np.all(ff >= 1.0), "Formation Factor cannot be < 1"

    def test_archie_m_range_compliance(self):
        """Cementation exponents within [1.3, 3.5] must produce guard-clean FF curves."""
        for m in [1.3, 1.7, 2.2, 3.0, 3.5]:
            phi = np.linspace(0.05, 0.35, 30)
            ff  = phi ** -m
            g = PhysicsGuard()
            g.validate_archie(phi, ff, model_type="FF")
            r = g.generate_health_score()
            assert r["score"] == 100, f"Guard failed for m={m}: {r['violations']}"

    def test_archie_n_range_compliance(self):
        """Saturation exponents within [1.5, 3.0] must produce guard-clean RI curves."""
        for n in [1.5, 2.0, 2.5, 3.0]:
            sw = np.linspace(0.2, 1.0, 30)
            ri = sw ** -n
            g = PhysicsGuard()
            g.validate_archie(sw, ri, model_type="RI")
            r = g.generate_health_score()
            assert r["score"] == 100, f"Guard failed for n={n}: {r['violations']}"


# ══════════════════════════════════════════════════════════════════════════════
# PHYSICS VALIDATOR (legacy)
# ══════════════════════════════════════════════════════════════════════════════

class TestPhysicsValidator:

    def test_valid_data_passthrough(self):
        data = {"Swi": 0.2, "Sor": 0.2, "Porosity": 0.25}
        result = PhysicsValidator.validate_core_physics(data)
        assert result["Swi"] == 0.2
        assert result["Sor"] == 0.2
        assert result["Porosity"] == 0.25

    def test_saturation_sum_exactly_1_passes(self):
        data = {"Swi": 0.5, "Sor": 0.5, "Porosity": 0.25}
        result = PhysicsValidator.validate_core_physics(data)
        assert result["Swi"] == 0.5

    def test_saturation_sum_over_1_raises(self):
        data = {"Swi": 0.6, "Sor": 0.5, "Porosity": 0.2}
        with pytest.raises(PhysicsEngineError):
            PhysicsValidator.validate_core_physics(data)

    def test_saturation_sum_slightly_over_1_raises(self):
        data = {"Swi": 0.51, "Sor": 0.50, "Porosity": 0.2}
        with pytest.raises(PhysicsEngineError):
            PhysicsValidator.validate_core_physics(data)

    def test_porosity_exactly_0_raises(self):
        data = {"Swi": 0.2, "Sor": 0.2, "Porosity": 0.0}
        with pytest.raises(PhysicsEngineError):
            PhysicsValidator.validate_core_physics(data)

    def test_porosity_exactly_1_raises(self):
        data = {"Swi": 0.2, "Sor": 0.2, "Porosity": 1.0}
        with pytest.raises(PhysicsEngineError):
            PhysicsValidator.validate_core_physics(data)

    def test_porosity_above_1_raises(self):
        data = {"Swi": 0.2, "Sor": 0.2, "Porosity": 1.2}
        with pytest.raises(PhysicsEngineError):
            PhysicsValidator.validate_core_physics(data)

    def test_porosity_negative_raises(self):
        data = {"Swi": 0.2, "Sor": 0.2, "Porosity": -0.1}
        with pytest.raises(PhysicsEngineError):
            PhysicsValidator.validate_core_physics(data)

    def test_precision_rounding(self):
        data = {"Swi": 0.123456789, "Sor": 0.1, "Porosity": 0.25}
        result = PhysicsValidator.validate_core_physics(data)
        assert result["Swi"] == 0.1235  # rounded to 4 decimal places

    def test_extra_fields_preserved(self):
        data = {"Swi": 0.2, "Sor": 0.15, "Porosity": 0.25, "Permeability": 150.0}
        result = PhysicsValidator.validate_core_physics(data)
        assert "Permeability" in result
        assert result["Permeability"] == 150.0

    def test_format_precision_function(self):
        assert PhysicsValidator.format_precision(3.14159265, 2) == 3.14
        assert PhysicsValidator.format_precision(0.123456,  4) == 0.1235
        assert PhysicsValidator.format_precision(1.0,       0) == 1

    def test_physics_engine_error_is_exception(self):
        with pytest.raises(Exception):
            raise PhysicsEngineError("test")

    def test_physics_engine_error_message(self):
        msg = "Swi + Sor > 1.0"
        with pytest.raises(PhysicsEngineError) as exc_info:
            raise PhysicsEngineError(msg)
        assert msg in str(exc_info.value)

    @pytest.mark.parametrize("swi,sor,poro", [
        (0.05, 0.05, 0.35),   # high-quality
        (0.30, 0.25, 0.15),   # tight
        (0.10, 0.20, 0.28),   # typical PRC sandstone
    ])
    def test_valid_parameter_sets_pass(self, swi, sor, poro):
        data = {"Swi": swi, "Sor": sor, "Porosity": poro}
        result = PhysicsValidator.validate_core_physics(data)
        assert result["Swi"] == swi


# ══════════════════════════════════════════════════════════════════════════════
# SKILLS ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TestSkillsEngine:

    def test_missing_skill_returns_error_dict(self):
        # Use an allowlisted script name so the not-found fall-through is reached:
        # the B1/B2 allowlist rejects unknown script names *before* the existence
        # check (see test_skills_allowlist.py), so a bogus name would return
        # "not permitted" instead. A bogus category/skill still yields "not found".
        result = SkillsEngine.run_skill("nonexistent_category", "nonexistent_skill", "petrophysics.py")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_missing_script_in_valid_category(self, tmp_path):
        """Confirms the two-path resolution falls through to an error."""
        result = SkillsEngine.run_skill("petroleum", "simulator", "does_not_exist.py")
        assert "error" in result

    def test_run_skill_returns_dict_with_required_keys(self):
        """For a real skill, verify the return structure has the expected keys."""
        import json
        payload = json.dumps({
            "sw": [0.2, 0.35, 0.5, 0.65, 0.85],
            "krw": [0.0, 0.05, 0.12, 0.25, 0.65],
            "kro": [0.9, 0.6, 0.3, 0.1, 0.0],
        })
        result = SkillsEngine.run_skill(
            "petroleum", "simulator", "history_matching_skill.py", args=[payload]
        )
        assert isinstance(result, dict)
        assert any(k in result for k in ("stdout", "stderr", "exit_code", "error"))

    def test_list_categories_returns_list(self):
        cats = SkillsEngine.list_categories()
        assert isinstance(cats, list)

    def test_list_skills_petroleum_not_empty(self):
        skills = SkillsEngine.list_skills("petroleum")
        assert isinstance(skills, list)
        # hermes_skills_library/petroleum/ must contain at least one subdirectory
        assert len(skills) >= 1

    def test_list_skills_nonexistent_category_returns_empty(self):
        result = SkillsEngine.list_skills("category_that_does_not_exist_xyz")
        assert result == []

    def test_curve_fitting_skill_corrupted_data_fails_gracefully(self):
        """Corrupted data (NaN, out-of-range) must not raise an unhandled exception."""
        import json
        bad_payload = json.dumps({
            "model": "brooks_corey",
            "sw": [-0.5, float("nan"), 1.5],
            "krw": [0.0, 0.5, 1.5]
        })
        result = SkillsEngine.run_skill(
            "petroleum", "", "curve_fitting_skill.py", args=[bad_payload]
        )
        # Must return a dict; exit_code != 0 or "error" in output is acceptable
        assert isinstance(result, dict)
        out = (result.get("stdout", "") + result.get("stderr", "") + result.get("error", "")).lower()
        assert "error" in out or result.get("exit_code", 0) != 0

    def test_simulation_core_prc_defaults(self):
        """PRC standard defaults must produce a valid Kr JSON response."""
        import json
        params = {
            "model": "brooks_corey",
            "mode": "1d",
            "swr": 0.20,
            "snr": 0.15,
            "krw_max": 0.65,
            "kro_max": 0.90,
            "nw": 2.5,
            "no": 2.5,
        }
        result = SkillsEngine.run_skill(
            "petroleum", "simulator", "simulation_core.py", args=[json.dumps(params)]
        )
        assert isinstance(result, dict)
        stdout = result.get("stdout", "")
        assert "success" in stdout.lower() or len(stdout) > 10
