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

def test_validate_j_function():
    # Happy path
    guard = PhysicsGuard()
    j_valid = np.array([0.1, 0.4, 1.5])
    sw_valid = np.array([1.0, 0.9, 0.2])
    guard.validate_j_function(j_valid, sw_valid)
    score = guard.generate_health_score()
    assert score["score"] == 100

    # Negative J value
    guard_neg = PhysicsGuard()
    j_neg = np.array([-0.1, 0.4, 1.5])
    guard_neg.validate_j_function(j_neg)
    score_neg = guard_neg.generate_health_score()
    assert score_neg["score"] < 100
    assert "J_NEGATIVE" in [v["rule"] for v in score_neg["violations"]]

    # Entry IFT Mismatch (J > 0.5 at Sw < 0.95)
    guard_ift = PhysicsGuard()
    j_ift = np.array([0.1, 0.6, 1.5])
    sw_ift = np.array([1.0, 0.9, 0.2])
    guard_ift.validate_j_function(j_ift, sw_ift)
    score_ift = guard_ift.generate_health_score()
    assert score_ift["score"] < 100
    assert "J_ENTRY_IFT_MISMATCH" in [v["rule"] for v in score_ift["violations"]]

    # Maximum J Impossible (J > 2.0)
    guard_max = PhysicsGuard()
    j_max = np.array([0.1, 0.4, 3.0])
    guard_max.validate_j_function(j_max)
    score_max = guard_max.generate_health_score()
    assert score_max["score"] < 100
    assert "J_MAX_IMPOSSIBLE" in [v["rule"] for v in score_max["violations"]]

    # Catastrophic Maximum J (J > 5.0)
    guard_cat = PhysicsGuard()
    j_cat = np.array([0.1, 0.4, 6.0])
    guard_cat.validate_j_function(j_cat)
    score_cat = guard_cat.generate_health_score()
    assert score_cat["score"] < 100
    assert "J_MAX_IMPOSSIBLE" in [v["rule"] for v in score_cat["violations"]]
    assert "J_CATASTROPHIC" in [v["rule"] for v in score_cat["violations"]]
