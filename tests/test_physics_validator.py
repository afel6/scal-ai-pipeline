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

def test_validate_saturation_endpoints_valid():
    guard = PhysicsGuard()
    guard.validate_saturation_endpoints(swi=0.2, sor=0.2, sample="Test1")
    score_info = guard.generate_health_score()
    assert score_info["score"] == 100
    assert score_info["grade"] == "A"
    assert len(score_info["violations"]) == 0

def test_validate_saturation_endpoints_mass_conservation_violation():
    guard = PhysicsGuard()
    guard.validate_saturation_endpoints(swi=0.6, sor=0.5, sample="Test2")
    score_info = guard.generate_health_score()
    violations = score_info["violations"]
    assert any(v["rule"] == "SAT_MASS_CONSERVATION" for v in violations)

def test_validate_saturation_endpoints_swi_range_violation():
    guard = PhysicsGuard()
    guard.validate_saturation_endpoints(swi=0.85, sor=0.1, sample="Test3")
    score_info = guard.generate_health_score()
    violations = score_info["violations"]
    assert any(v["rule"] == "SWI_RANGE" for v in violations)

def test_validate_saturation_endpoints_sor_range_violation():
    guard = PhysicsGuard()
    guard.validate_saturation_endpoints(swi=0.2, sor=0.55, sample="Test4")
    score_info = guard.generate_health_score()
    violations = score_info["violations"]
    assert any(v["rule"] == "SOR_RANGE" for v in violations)

def test_validate_saturation_endpoints_multiple_violations():
    guard = PhysicsGuard()
    # Violates mass conservation, SWI range, and SOR range
    guard.validate_saturation_endpoints(swi=0.85, sor=0.55, sample="Test5")
    score_info = guard.generate_health_score()
    violations = [v["rule"] for v in score_info["violations"]]
    assert "SAT_MASS_CONSERVATION" in violations
    assert "SWI_RANGE" in violations
    assert "SOR_RANGE" in violations
