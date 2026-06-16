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

def test_validate_archie():
    guard = PhysicsGuard()

    # Empty inputs
    guard.validate_archie([], [])
    score = guard.generate_health_score()
    assert score["score"] == 100

    # Valid FF
    guard.validate_archie([0.1, 0.2], [10.0, 5.0], model_type="FF")
    score = guard.generate_health_score()
    assert score["score"] == 100

    # FF monotonicity violation (increases as porosity increases)
    guard_bad_ff_mono = PhysicsGuard()
    guard_bad_ff_mono.validate_archie([0.1, 0.2], [5.0, 10.0], model_type="FF")
    score_bad_ff_mono = guard_bad_ff_mono.generate_health_score()
    assert "FF_MONOTONICITY" in [v["rule"] for v in score_bad_ff_mono["violations"]]

    # FF range violation (< 1.0)
    guard_bad_ff_range = PhysicsGuard()
    guard_bad_ff_range.validate_archie([0.1, 0.2], [0.5, 0.4], model_type="FF")
    score_bad_ff_range = guard_bad_ff_range.generate_health_score()
    assert "FF_RANGE" in [v["rule"] for v in score_bad_ff_range["violations"]]

    # Valid RI
    guard_ri = PhysicsGuard()
    guard_ri.validate_archie([0.5, 1.0], [4.0, 1.0], model_type="RI")
    score_ri = guard_ri.generate_health_score()
    assert score_ri["score"] == 100

    # RI monotonicity violation (increases as Sw increases)
    guard_bad_ri_mono = PhysicsGuard()
    guard_bad_ri_mono.validate_archie([0.5, 1.0], [1.0, 4.0], model_type="RI")
    score_bad_ri_mono = guard_bad_ri_mono.generate_health_score()
    assert "RI_MONOTONICITY" in [v["rule"] for v in score_bad_ri_mono["violations"]]

    # RI range violation (< 1.0)
    guard_bad_ri_range = PhysicsGuard()
    guard_bad_ri_range.validate_archie([0.5, 1.0], [0.8, 0.5], model_type="RI")
    score_bad_ri_range = guard_bad_ri_range.generate_health_score()
    assert "RI_RANGE" in [v["rule"] for v in score_bad_ri_range["violations"]]

    # RI endpoint violation (> 1.1 at max Sw)
    guard_bad_ri_end = PhysicsGuard()
    guard_bad_ri_end.validate_archie([0.5, 1.0], [4.0, 1.5], model_type="RI")
    score_bad_ri_end = guard_bad_ri_end.generate_health_score()
    assert "RI_ENDPOINT" in [v["rule"] for v in score_bad_ri_end["violations"]]

def test_validate_pc():
    guard = PhysicsGuard()

    # Empty inputs
    guard.validate_pc([], [])
    score = guard.generate_health_score()
    assert score["score"] == 100

    # Valid drainage
    guard_drain = PhysicsGuard()
    guard_drain.validate_pc([0.2, 0.8], [100.0, 10.0], cycle="drainage")
    score_drain = guard_drain.generate_health_score()
    assert score_drain["score"] == 100

    # Valid imbibition (negative Pc allowed)
    guard_imb = PhysicsGuard()
    guard_imb.validate_pc([0.2, 0.8], [10.0, -10.0], cycle="imbibition")
    score_imb = guard_imb.generate_health_score()
    assert score_imb["score"] == 100

    # Pc monotonicity violation (increases as Sw increases)
    guard_bad_mono = PhysicsGuard()
    guard_bad_mono.validate_pc([0.2, 0.8], [10.0, 100.0])
    score_bad_mono = guard_bad_mono.generate_health_score()
    assert "PC_MONOTONICITY" in [v["rule"] for v in score_bad_mono["violations"]]

    # Pc range violation (negative in drainage)
    guard_bad_range = PhysicsGuard()
    guard_bad_range.validate_pc([0.2, 0.8], [10.0, -5.0], cycle="drainage")
    score_bad_range = guard_bad_range.generate_health_score()
    assert "PC_RANGE" in [v["rule"] for v in score_bad_range["violations"]]


def test_validate_compressibility_empty():
    guard = PhysicsGuard()
    # Test with array of zeros that gets filtered out to an empty array
    guard.validate_compressibility(np.array([0.0, 0.0]))
    score = guard.generate_health_score()
    assert score["score"] == 100

def test_validate_j_function_entry_no_mask():
    guard = PhysicsGuard()
    # Provide Sw array where Sw < 0.95 is false everywhere
    j_arr = np.array([0.1, 0.2, 0.3])
    sw_arr = np.array([0.96, 0.97, 0.98])
    guard.validate_j_function(j_arr, sw_arr)
    score = guard.generate_health_score()
    assert score["score"] == 100


def test_validate_j_function_boundaries():
    guard = PhysicsGuard()

    # Boundary: Exactly 0.0 (Should not trigger J_NEGATIVE)
    guard.validate_j_function(np.array([0.0, 0.1]))
    score = guard.generate_health_score()
    assert "J_NEGATIVE" not in [v["rule"] for v in score["violations"]]

    # Boundary: -1e-7 (Should not trigger J_NEGATIVE due to < -1e-6 check)
    guard_neg_tiny = PhysicsGuard()
    guard_neg_tiny.validate_j_function(np.array([-1e-7, 0.1]))
    score_neg_tiny = guard_neg_tiny.generate_health_score()
    assert "J_NEGATIVE" not in [v["rule"] for v in score_neg_tiny["violations"]]

    # Boundary: J at entry exactly 0.5 (Valid)
    guard_entry_exact = PhysicsGuard()
    guard_entry_exact.validate_j_function(np.array([0.5, 0.6]), np.array([0.9, 0.8]))
    score_entry_exact = guard_entry_exact.generate_health_score()
    assert "J_ENTRY_IFT_MISMATCH" not in [v["rule"] for v in score_entry_exact["violations"]]

    # Boundary: J at entry exactly 0.5001 (Invalid)
    guard_entry_over = PhysicsGuard()
    guard_entry_over.validate_j_function(np.array([0.5001, 0.6]), np.array([0.9, 0.8]))
    score_entry_over = guard_entry_over.generate_health_score()
    assert "J_ENTRY_IFT_MISMATCH" in [v["rule"] for v in score_entry_over["violations"]]

    # Boundary: Sw = 0.95 (Should not be considered entry due to < 0.95 check)
    guard_sw_boundary = PhysicsGuard()
    guard_sw_boundary.validate_j_function(np.array([0.6, 0.7]), np.array([0.95, 0.95]))
    score_sw_boundary = guard_sw_boundary.generate_health_score()
    assert "J_ENTRY_IFT_MISMATCH" not in [v["rule"] for v in score_sw_boundary["violations"]]

    # Boundary: Max J exactly 2.0 (Valid)
    guard_max_exact = PhysicsGuard()
    guard_max_exact.validate_j_function(np.array([1.0, 2.0]))
    score_max_exact = guard_max_exact.generate_health_score()
    assert "J_MAX_IMPOSSIBLE" not in [v["rule"] for v in score_max_exact["violations"]]

    # Boundary: Max J exactly 2.0001 (Invalid)
    guard_max_over = PhysicsGuard()
    guard_max_over.validate_j_function(np.array([1.0, 2.0001]))
    score_max_over = guard_max_over.generate_health_score()
    assert "J_MAX_IMPOSSIBLE" in [v["rule"] for v in score_max_over["violations"]]

    # Boundary: Max J exactly 5.0 (Triggers MAX_IMPOSSIBLE but NOT CATASTROPHIC)
    guard_max_cat_exact = PhysicsGuard()
    guard_max_cat_exact.validate_j_function(np.array([1.0, 5.0]))
    score_max_cat_exact = guard_max_cat_exact.generate_health_score()
    violations_cat_exact = [v["rule"] for v in score_max_cat_exact["violations"]]
    assert "J_MAX_IMPOSSIBLE" in violations_cat_exact
    assert "J_CATASTROPHIC" not in violations_cat_exact

    # Boundary: Max J exactly 5.0001 (Triggers CATASTROPHIC)
    guard_max_cat_over = PhysicsGuard()
    guard_max_cat_over.validate_j_function(np.array([1.0, 5.0001]))
    score_max_cat_over = guard_max_cat_over.generate_health_score()
    assert "J_CATASTROPHIC" in [v["rule"] for v in score_max_cat_over["violations"]]

    # Edge case: Explicitly pass sw_arr=None
    guard_none_sw = PhysicsGuard()
    guard_none_sw.validate_j_function(np.array([0.6, 0.7]), sw_arr=None)
    score_none_sw = guard_none_sw.generate_health_score()
    assert "J_ENTRY_IFT_MISMATCH" not in [v["rule"] for v in score_none_sw["violations"]]
