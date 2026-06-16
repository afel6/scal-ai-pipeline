import pytest
from prc_physics import fit_brooks_corey

def test_fit_brooks_corey_happy_path():
    data = [
        {"Water_Saturation": "20.0", "Pc_psi": 100.0, "Krw": 0.0, "Kro": 1.0},
        {"Water_Saturation": "50.0", "Pc_psi": 10.0, "Krw": 0.1, "Kro": 0.5},
        {"Water_Saturation": "80.0", "Pc_psi": 1.0, "Krw": 1.0, "Kro": 0.0}
    ]
    result = fit_brooks_corey(data)
    assert "Swi" in result
    assert "Sor" in result
    assert "Pd_psi" in result
    assert "lambda" in result
    assert "nw" in result
    assert "no" in result
    assert "krw_max" in result
    assert "krnw_max" in result

    assert result["Swi"] == 0.2
    assert result["Sor"] == 0.2

def test_fit_brooks_corey_empty_input():
    assert fit_brooks_corey([]) == {}

def test_fit_brooks_corey_no_valid_rows():
    data = [
        {"Invalid_Key": 10.0},
        {"Another_Invalid": 20.0}
    ]
    assert fit_brooks_corey(data) == {}

def test_fit_brooks_corey_explicit_endpoints():
    data = [
        {"Water_Saturation_fraction": 0.2, "explicit_Swi": 0.15, "explicit_Sor": 0.15, "Pc_psi": 100},
        {"Water_Saturation_fraction": 0.8, "explicit_Swi": 0.15, "explicit_Sor": 0.15, "Pc_psi": 1}
    ]
    result = fit_brooks_corey(data)
    assert result["Swi"] == 0.15
    assert result["Sor"] == 0.15

def test_fit_brooks_corey_fractional_saturation():
    data = [
        {"Water_Saturation_fraction": 0.2, "Pc_psi": 100.0, "Krw": 0.0, "Kro": 1.0},
        {"Water_Saturation_fraction": 0.5, "Pc_psi": 10.0, "Krw": 0.1, "Kro": 0.5},
        {"Water_Saturation_fraction": 0.8, "Pc_psi": 1.0, "Krw": 1.0, "Kro": 0.0}
    ]
    result = fit_brooks_corey(data)
    assert result["Swi"] == 0.2
    assert result["Sor"] == 0.2
