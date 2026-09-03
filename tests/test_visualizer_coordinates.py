"""Unit tests for the decoupled coordinate generation in visualizer.py.

These exercise the pure ``extract_curve_coordinates`` core (no rendering) plus a
round-trip through the renderer to confirm the wrapper still writes files.
"""

import json
import os

from visualizer import extract_curve_coordinates, generate_plots


_SAMPLE = [
    {"Pressure_psi": 2000.0, "Porosity_percent": 17.8, "Air_Permeability_md": 42.1},
    {"Pressure_psi": 800.0, "Porosity_percent": 18.5, "Air_Permeability_md": 45.2},
    {"Pressure_psi": 1200.0, "Porosity_percent": 18.2, "Air_Permeability_md": 44.8},
]


def test_extract_returns_two_curves():
    payloads = extract_curve_coordinates(_SAMPLE)
    titles = {p["title"] for p in payloads}
    assert "Porosity vs. Overburden Pressure" in titles
    assert "Air Permeability vs. Overburden Pressure" in titles


def test_coordinates_sorted_by_pressure():
    payloads = extract_curve_coordinates(_SAMPLE)
    porosity = next(p for p in payloads if p["labels"] == ["Porosity"])
    assert porosity["x"] == [800.0, 1200.0, 2000.0]
    assert porosity["y"] == [18.5, 18.2, 17.8]


def test_payload_is_json_serializable():
    payloads = extract_curve_coordinates(_SAMPLE)
    json.dumps(payloads)  # must not raise


def test_null_values_are_dropped():
    data = [
        {"Pressure_psi": 1000.0, "Porosity_percent": None, "Air_Permeability_md": 40.0},
        {"Pressure_psi": 2000.0, "Porosity_percent": 17.0, "Air_Permeability_md": 38.0},
    ]
    payloads = extract_curve_coordinates(data)
    porosity = next(p for p in payloads if p["labels"] == ["Porosity"])
    # The null-porosity row is excluded; only the valid pressure remains.
    assert porosity["x"] == [2000.0]


def test_rows_without_pressure_are_skipped():
    data = [{"Porosity_percent": 18.0, "Air_Permeability_md": 40.0}]
    assert extract_curve_coordinates(data) == []


def test_generate_plots_still_renders(tmp_path):
    out_dir = str(tmp_path / "outputs")
    generate_plots(_SAMPLE, output_dir=out_dir)
    assert os.path.exists(os.path.join(out_dir, "porosity_vs_pressure.png"))
    assert os.path.exists(os.path.join(out_dir, "permeability_vs_pressure.png"))
    assert os.path.exists(os.path.join(out_dir, "validated_scal_data.json"))
