import pytest
from prc_physics import calculate_compressibility_sweep

def test_calculate_compressibility_sweep_empty_invalid():
    assert calculate_compressibility_sweep([]) == []
    assert calculate_compressibility_sweep(None) is None
    assert calculate_compressibility_sweep("not a list") == "not a list"

def test_calculate_compressibility_sweep_missing_data():
    data = [
        {"Pressure_psi": 1000}, # Missing Porosity
        {"Porosity_percent": 20}, # Missing Pressure
        {"Other": "Data"} # Missing both
    ]
    result = calculate_compressibility_sweep(data)
    for row in result:
        assert row["Pore_Volume_Compressibility_psi_inv"] is None
        assert row["Deduced_Lithology"] == "Unknown Matrix"

def test_calculate_compressibility_sweep_baseline():
    data = [
        {"Pressure_psi": 0.0, "Porosity_percent": 20.0, "Air_Permeability_md": 5.0}
    ]
    result = calculate_compressibility_sweep(data)
    assert result[0]["Pore_Volume_Compressibility_psi_inv"] == 0.0
    # phi=20, k=5, cp=0.0 -> fallback heuristic: not phi<15, not phi>25 -> Consolidated Sandstone
    assert result[0]["Deduced_Lithology"] == "Consolidated Sandstone"

def test_calculate_compressibility_sweep_valid():
    data = [
        {"Pressure_psi": 0.0, "Porosity_percent": 20.0},
        {"Pressure_psi": 1000.0, "Porosity_percent": 19.5}
    ]
    result = calculate_compressibility_sweep(data)

    assert result[0]["Pore_Volume_Compressibility_psi_inv"] == 0.0

    # cp = (1/20) * ((20 - 19.5) / 1000) = 0.05 * 0.0005 = 0.000025 (25e-6)
    expected_cp = round((1.0 / 20.0) * ((20.0 - 19.5) / 1000.0), 10)
    assert result[1]["Pore_Volume_Compressibility_psi_inv"] == expected_cp
    # cp is 25e-6 > 10e-6 -> Unconsolidated Sandstone
    assert result[1]["Deduced_Lithology"] == "Unconsolidated Sandstone"

def test_calculate_compressibility_sweep_lithology_youngs():
    data = [
        {"Pressure_psi": 0.0, "Porosity_percent": 20.0},
        # Rigid Carbonate: > 25 GPa
        {"Pressure_psi": 1000.0, "Porosity_percent": 19.5, "Youngs_Modulus_gpa": 30.0},
        # Unconsolidated Sandstone: < 10 GPa
        {"Pressure_psi": 2000.0, "Porosity_percent": 19.0, "Youngs_Modulus_gpa": 5.0},
        # Consolidated Sandstone: 10 - 25 GPa
        {"Pressure_psi": 3000.0, "Porosity_percent": 18.5, "Youngs_Modulus_gpa": 20.0},
        # Test with psi instead of gpa: 4,000,000 psi ~= 27.5 GPa (> 25 GPa -> Rigid)
        {"Pressure_psi": 4000.0, "Porosity_percent": 18.0, "Youngs_Modulus_psi": 4000000.0}
    ]
    result = calculate_compressibility_sweep(data)
    assert result[1]["Deduced_Lithology"] == "Rigid Carbonate"
    assert result[2]["Deduced_Lithology"] == "Unconsolidated Sandstone"
    assert result[3]["Deduced_Lithology"] == "Consolidated Sandstone"
    assert result[4]["Deduced_Lithology"] == "Rigid Carbonate"

def test_calculate_compressibility_sweep_lithology_heuristics():
    data = [
        {"Pressure_psi": 0.0, "Porosity_percent": 20.0},
        # cp < 4e-6 -> Rigid Carbonate. dp=1000. phi_delta = 20 * cp * dp = 20 * 3e-6 * 1000 = 0.06
        {"Pressure_psi": 1000.0, "Porosity_percent": 19.94},
        # cp >= 10e-6 -> Unconsolidated. dp=2000. phi_delta = 20 * 15e-6 * 2000 = 0.6
        {"Pressure_psi": 2000.0, "Porosity_percent": 19.4},
        # cp between 4e-6 and 10e-6 -> Consolidated. dp=3000. phi_delta = 20 * 6e-6 * 3000 = 0.36
        {"Pressure_psi": 3000.0, "Porosity_percent": 19.64}
    ]
    result = calculate_compressibility_sweep(data)
    assert result[1]["Deduced_Lithology"] == "Rigid Carbonate"
    assert result[2]["Deduced_Lithology"] == "Unconsolidated Sandstone"
    assert result[3]["Deduced_Lithology"] == "Consolidated Sandstone"

def test_calculate_compressibility_sweep_boundaries():
    data = [
        # Sweep 1
        {"Pressure_psi": 100.0, "Porosity_percent": 20.0},
        {"Pressure_psi": 1000.0, "Porosity_percent": 19.5},
        # Sweep 2 starts (pressure drops to 200, setting new baseline)
        {"Pressure_psi": 200.0, "Porosity_percent": 15.0},
        {"Pressure_psi": 2000.0, "Porosity_percent": 14.5}
    ]
    result = calculate_compressibility_sweep(data)
    # Sweep 1 calculations
    assert result[0]["Pore_Volume_Compressibility_psi_inv"] == 0.0 # First row is baseline
    cp1 = round((1.0 / 20.0) * ((20.0 - 19.5) / 900.0), 10)
    assert result[1]["Pore_Volume_Compressibility_psi_inv"] == cp1

    # Sweep 2 calculations
    assert result[2]["Pore_Volume_Compressibility_psi_inv"] == 0.0 # New baseline because pressure dropped
    cp2 = round((1.0 / 15.0) * ((15.0 - 14.5) / 1800.0), 10)
    assert result[3]["Pore_Volume_Compressibility_psi_inv"] == cp2

def test_calculate_compressibility_sweep_error_handling():
    data = [
        {"Pressure_psi": 0.0, "Porosity_percent": 20.0},
        # Invalid porosity increase -> raises ValueError in calculate_pore_compressibility
        {"Pressure_psi": 1000.0, "Porosity_percent": 21.0}
    ]
    result = calculate_compressibility_sweep(data)
    assert result[1]["Pore_Volume_Compressibility_psi_inv"] is None

def test_calculate_compressibility_sweep_physics_guard():
    data = [
        {"Pressure_psi": 0.0, "Porosity_percent": 20.0},
        # High valid cp
        {"Pressure_psi": 1000.0, "Porosity_percent": 19.5},
        # Catastrophic cp > 100e-6 -> will trigger physics guard violations
        {"Pressure_psi": 2000.0, "Porosity_percent": 10.0}
    ]
    result = calculate_compressibility_sweep(data)

    # Audit should be attached to the last row
    assert "_cp_physics_audit" in result[-1]
    audit = result[-1]["_cp_physics_audit"]
    assert "violations" in audit
    # There should be violations because of the catastrophic drop in porosity (high cp)
    assert any("CP_CATASTROPHIC" == v.get("rule") for v in audit["violations"])
