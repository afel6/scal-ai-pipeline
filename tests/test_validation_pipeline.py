import os
import json
from data_validator import validate_scal_data
from visualizer import generate_plots

def test_data_validator_valid():
    valid_data = [
        {
            "Pressure_psi": 800.0,
            "Porosity_percent": 18.5,
            "Air_Permeability_md": 45.2,
            "Klinkenberg_Permeability_md": 44.0,
            "Water_Saturation_fraction": 1.0,
            "Formation_Factor": 20.0
        },
        {
            "Pressure_psi": 1200.0,
            "Porosity_percent": 18.2,
            "Air_Permeability_md": 44.8,
            "Klinkenberg_Permeability_md": 43.5,
            "Water_Saturation_fraction": 0.85,
            "Formation_Factor": 24.3
        }
    ]
    result = validate_scal_data(valid_data)
    assert result["status"] == "success"
    assert len(result["data"]) == 2

def test_data_validator_invalid_porosity():
    invalid_data = [
        {
            "Pressure_psi": 800.0,
            "Porosity_percent": 105.0,  # Invalid (> 100)
            "Air_Permeability_md": 45.2
        }
    ]
    result = validate_scal_data(invalid_data)
    assert result["status"] == "error"
    assert any("Porosity value out of bounds" in err for err in result["errors"])

def test_data_validator_invalid_perm():
    invalid_data = [
        {
            "Pressure_psi": 800.0,
            "Porosity_percent": 18.5,
            "Air_Permeability_md": -2.3  # Invalid (negative)
        }
    ]
    result = validate_scal_data(invalid_data)
    assert result["status"] == "error"
    assert any("cannot be negative" in err for err in result["errors"])

def test_data_validator_invalid_pressure_sequence():
    invalid_sequence = [
        {
            "Pressure_psi": 1200.0,
            "Porosity_percent": 18.5,
            "Air_Permeability_md": 45.2
        },
        {
            "Pressure_psi": 800.0,  # Invalid (drop in pressure)
            "Porosity_percent": 18.2,
            "Air_Permeability_md": 44.8
        }
    ]
    result = validate_scal_data(invalid_sequence)
    assert result["status"] == "error"
    assert any("must be strictly increasing" in err for err in result["errors"])

def test_data_validator_null_values():
    null_data = [
        {
            "Pressure_psi": 800.0,
            "Porosity_percent": None,  # Required: should trigger error
            "Air_Permeability_md": 45.2
        }
    ]
    result = validate_scal_data(null_data)
    assert result["status"] == "error"
    assert any("Missing data (null)" in err for err in result["errors"])

def test_data_validator_optional_null_warnings():
    optional_null_data = [
        {
            "Pressure_psi": 800.0,
            "Porosity_percent": 18.5,
            "Air_Permeability_md": 45.2,
            "Klinkenberg_Permeability_md": None,  # Optional: should trigger warning, not error
            "Formation_Factor": None              # Optional: should trigger warning, not error
        }
    ]
    result = validate_scal_data(optional_null_data)
    assert result["status"] == "success"
    assert len(result["warnings"]) == 2
    assert any("Klinkenberg_Permeability_md" in w for w in result["warnings"])
    assert any("Formation_Factor" in w for w in result["warnings"])

def test_visualizer_generation(tmp_path):
    test_data = [
        {
            "Pressure_psi": 800.0,
            "Porosity_percent": 18.5,
            "Air_Permeability_md": 45.2
        },
        {
            "Pressure_psi": 1200.0,
            "Porosity_percent": 18.2,
            "Air_Permeability_md": 44.8
        }
    ]
    
    # Use standard generate_plots
    output_dir = str(tmp_path)
    generate_plots(test_data, output_dir=output_dir)
    
    # Verify outputs
    porosity_plot = os.path.join(output_dir, "porosity_vs_pressure.png")
    perm_plot = os.path.join(output_dir, "permeability_vs_pressure.png")
    json_export = os.path.join(output_dir, "validated_scal_data.json")
    
    assert os.path.exists(porosity_plot)
    assert os.path.exists(perm_plot)
    assert os.path.exists(json_export)
    
    # Verify exported JSON content matches
    with open(json_export, 'r', encoding='utf-8') as f:
        exported_data = json.load(f)
    assert exported_data == test_data
