import sys
from pathlib import Path

# Add root/src to path just in case
sys.path.append(str(Path(__file__).parent.parent))

from src.utils.units import (
    convert_pressure,
    convert_temperature,
    convert_permeability,
    convert_viscosity,
    detect_unit,
    normalize_value,
)

def test_unit_conversions():
    # Pressure conversions
    assert abs(convert_pressure(1.0, "psi") - 1.0) < 1e-5
    assert abs(convert_pressure(1.0, "bar") - 14.5037738) < 1e-4
    assert abs(convert_pressure(100.0, "kPa") - 14.5037738) < 1e-4

    # Temperature conversions
    assert abs(convert_temperature(200.0, "F") - 200.0) < 1e-5
    assert abs(convert_temperature(100.0, "C") - 212.0) < 1e-4
    assert abs(convert_temperature(300.0, "K") - 80.33) < 1e-2

    # Permeability conversions
    assert abs(convert_permeability(150.0, "mD") - 150.0) < 1e-5
    assert abs(convert_permeability(1.5, "D") - 1500.0) < 1e-5

    # Viscosity conversions
    assert abs(convert_viscosity(2.5, "cp") - 2.5) < 1e-5
    assert abs(convert_viscosity(0.0025, "Pa.s") - 2.5) < 1e-5

def test_detect_unit():
    assert detect_unit("Pressure (bar)") == ("pressure", "bar")
    assert detect_unit("T [C]") == ("temperature", "C")
    assert detect_unit("permeability (D)") == ("permeability", "D")
    assert detect_unit("Viscosity (Pa.s)") == ("viscosity", "Pa.s")
    assert detect_unit("No unit header") is None

def test_normalize_value():
    assert abs(normalize_value(2.0, "pressure", "bar") - 29.0075476) < 1e-4
    assert abs(normalize_value(100.0, "temperature", "celsius") - 212.0) < 1e-4
