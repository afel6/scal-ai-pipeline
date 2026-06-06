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

def test_physics_guard_compressibility():
    # Valid compressibility
    guard = PhysicsGuard()
    cp_valid = [5e-6, 10e-6, 25e-6]
    guard.validate_compressibility(cp_valid)
    score = guard.generate_health_score()
    assert score["score"] == 100

    # Negative compressibility
    guard_neg = PhysicsGuard()
    cp_neg = [5e-6, -2e-6, 10e-6]
    guard_neg.validate_compressibility(cp_neg)
    score_neg = guard_neg.generate_health_score()
    assert score_neg["score"] < 100
    assert "CP_NEGATIVE" in [v["rule"] for v in score_neg["violations"]]

    # High compressibility (>50e-6)
    guard_high = PhysicsGuard()
    cp_high = [10e-6, 60e-6]
    guard_high.validate_compressibility(cp_high)
    score_high = guard_high.generate_health_score()
    assert score_high["score"] < 100
    assert "CP_MAX_IMPOSSIBLE" in [v["rule"] for v in score_high["violations"]]

    # Catastrophic compressibility (>100e-6)
    guard_catastrophic = PhysicsGuard()
    cp_catastrophic = [10e-6, 150e-6]
    guard_catastrophic.validate_compressibility(cp_catastrophic)
    score_catastrophic = guard_catastrophic.generate_health_score()
    assert score_catastrophic["score"] < 100
    rules = [v["rule"] for v in score_catastrophic["violations"]]
    assert "CP_MAX_IMPOSSIBLE" in rules
    assert "CP_CATASTROPHIC" in rules

    # Edge cases (nan, inf, 0)
    # The validate_compressibility method filters out non-finite values (np.nan, np.inf)
    # and zero values, so an array containing only these will result in an empty valid
    # array and no violations will be flagged.
    guard_edge = PhysicsGuard()
    cp_edge = [0.0, np.nan, np.inf]
    guard_edge.validate_compressibility(cp_edge)
    score_edge = guard_edge.generate_health_score()
    assert score_edge["score"] == 100
