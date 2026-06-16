import pytest
import numpy as np
from physics_validator import PhysicsGuard, PhysicsValidator, PhysicsEngineError

def test_physics_validator_core_physics():
    # Valid data
    data = {"Swi": 0.2, "Sor": 0.2, "Porosity": 0.25}
    valid_data = PhysicsValidator.validate_core_physics(data)
    assert valid_data["Swi"] == 0.2
    assert valid_data["Sor"] == 0.2
    assert valid_data["Porosity"] == 0.25

    # Invalid saturation
    data_bad_sat = {"Swi": 0.6, "Sor": 0.5, "Porosity": 0.2}
    with pytest.raises(PhysicsEngineError):
        PhysicsValidator.validate_core_physics(data_bad_sat)

    # Invalid porosity
    data_bad_poro = {"Swi": 0.2, "Sor": 0.2, "Porosity": 1.2}
    with pytest.raises(PhysicsEngineError):
        PhysicsValidator.validate_core_physics(data_bad_poro)

def test_physics_guard_kr():
    guard = PhysicsGuard()
    # Good kr curve
    sw = np.linspace(0.2, 0.8, 10)
    krw = np.linspace(0, 0.5, 10)
    kro = np.linspace(0.8, 0, 10)
    guard.validate_kr(sw, krw, kro)
    score_info = guard.generate_health_score()
    assert score_info["score"] == 100
    assert score_info["grade"] == "A"

    # Bad kr curve: Krw goes down, Kro goes up
    guard_bad = PhysicsGuard()
    krw_bad = np.linspace(0.5, 0, 10)
    kro_bad = np.linspace(0, 0.8, 10)
    guard_bad.validate_kr(sw, krw_bad, kro_bad)
    score_info_bad = guard_bad.generate_health_score()
    assert score_info_bad["score"] < 100
    assert "KRW_MONOTONICITY" in [v["rule"] for v in score_info_bad["violations"]]

def test_physics_guard_micp():
    guard = PhysicsGuard()
    pc = np.linspace(1, 100, 10)
    hg_sat = np.linspace(0.05, 0.9, 10)
    guard.validate_micp(pc, hg_sat)
    score = guard.generate_health_score()
    assert score["score"] == 100

    guard_bad = PhysicsGuard()
    pc_bad = np.linspace(-10, 100, 10)
    guard_bad.validate_micp(pc_bad, hg_sat)
    score_bad = guard_bad.generate_health_score()
    assert score_bad["score"] < 100
    assert "MICP_NEGATIVE_PC" in [v["rule"] for v in score_bad["violations"]]

def test_validate_archie_parameters():
    guard = PhysicsGuard()
    # Good parameters
    guard.validate_archie_parameters(a=1.0, m=2.0, b=1.0, n=2.0)
    score_info = guard.generate_health_score()
    assert score_info["score"] == 100

    # Bad parameters: out of bounds
    guard_bad = PhysicsGuard()
    guard_bad.validate_archie_parameters(a=0.1, m=1.0, b=2.0, n=4.0)
    score_info_bad = guard_bad.generate_health_score()
    assert score_info_bad["score"] < 100
    violations = [v["rule"] for v in score_info_bad["violations"]]
    assert "ARCHIE_A_RANGE" in violations
    assert "ARCHIE_M_RANGE" in violations
    assert "ARCHIE_B_RANGE" in violations
    assert "ARCHIE_N_RANGE" in violations

def test_validate_saturation_endpoints():
    guard = PhysicsGuard()
    # Good saturation
    guard.validate_saturation_endpoints(swi=0.2, sor=0.2)
    score_info = guard.generate_health_score()
    assert score_info["score"] == 100

    # Bad saturation: mass conservation
    guard_mass = PhysicsGuard()
    guard_mass.validate_saturation_endpoints(swi=0.6, sor=0.5)
    score_mass = guard_mass.generate_health_score()
    assert score_mass["score"] < 100
    violations_mass = [v["rule"] for v in score_mass["violations"]]
    assert "SAT_MASS_CONSERVATION" in violations_mass

    # Bad saturation: extreme Swi and Sor
    guard_extreme = PhysicsGuard()
    # Swi > 0.8 and Sor > 0.5 (but Swi+Sor < 1.0 is impossible here, so we test them separately to just hit the range warnings)
    guard_extreme.validate_saturation_endpoints(swi=0.85, sor=0.1)
    score_extreme = guard_extreme.generate_health_score()
    violations_extreme = [v["rule"] for v in score_extreme["violations"]]
    assert "SWI_RANGE" in violations_extreme

    guard_extreme2 = PhysicsGuard()
    guard_extreme2.validate_saturation_endpoints(swi=0.1, sor=0.55)
    score_extreme2 = guard_extreme2.generate_health_score()
    violations_extreme2 = [v["rule"] for v in score_extreme2["violations"]]
    assert "SOR_RANGE" in violations_extreme2

def test_validate_j_function():
    guard = PhysicsGuard()
    # Good J-function
    j_arr = np.array([0.1, 0.2, 0.3])
    sw_arr = np.array([0.9, 0.8, 0.7])
    guard.validate_j_function(j_arr, sw_arr)
    score = guard.generate_health_score()
    assert score["score"] == 100

    # Negative J-function
    guard_neg = PhysicsGuard()
    guard_neg.validate_j_function(np.array([-0.1, 0.2, 0.3]))
    score_neg = guard_neg.generate_health_score()
    assert "J_NEGATIVE" in [v["rule"] for v in score_neg["violations"]]

    # Max J > 2.0
    guard_max = PhysicsGuard()
    guard_max.validate_j_function(np.array([0.1, 2.5, 0.3]))
    score_max = guard_max.generate_health_score()
    assert "J_MAX_IMPOSSIBLE" in [v["rule"] for v in score_max["violations"]]

    # Max J > 5.0
    guard_cat = PhysicsGuard()
    guard_cat.validate_j_function(np.array([0.1, 5.5, 0.3]))
    score_cat = guard_cat.generate_health_score()
    assert "J_CATASTROPHIC" in [v["rule"] for v in score_cat["violations"]]

    # J entry mismatch
    guard_entry = PhysicsGuard()
    guard_entry.validate_j_function(np.array([0.6, 0.7, 0.8]), np.array([0.9, 0.8, 0.7]))
    score_entry = guard_entry.generate_health_score()
    assert "J_ENTRY_IFT_MISMATCH" in [v["rule"] for v in score_entry["violations"]]

def test_validate_compressibility():
    guard = PhysicsGuard()
    # Good cp
    cp_arr = np.array([10e-6, 20e-6])
    guard.validate_compressibility(cp_arr)
    score = guard.generate_health_score()
    assert score["score"] == 100

    # Negative cp
    guard_neg = PhysicsGuard()
    guard_neg.validate_compressibility(np.array([-5e-6, 10e-6]))
    score_neg = guard_neg.generate_health_score()
    assert "CP_NEGATIVE" in [v["rule"] for v in score_neg["violations"]]

    # Max cp > 50e-6
    guard_max = PhysicsGuard()
    guard_max.validate_compressibility(np.array([10e-6, 60e-6]))
    score_max = guard_max.generate_health_score()
    assert "CP_MAX_IMPOSSIBLE" in [v["rule"] for v in score_max["violations"]]

    # Max cp > 100e-6
    guard_cat = PhysicsGuard()
    guard_cat.validate_compressibility(np.array([10e-6, 110e-6]))
    score_cat = guard_cat.generate_health_score()
    assert "CP_CATASTROPHIC" in [v["rule"] for v in score_cat["violations"]]


def test_validate_micp_constant_saturation():
    guard = PhysicsGuard()
    pc = np.linspace(1, 100, 10)
    hg_sat_const = np.full(10, 0.5)
    guard.validate_micp(pc, hg_sat_const)
    score = guard.generate_health_score()
    assert score["score"] < 100
    violations = [v["rule"] for v in score["violations"]]
    assert "MICP_CONSTANT_SATURATION" in violations

