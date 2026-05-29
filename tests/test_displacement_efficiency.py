"""
Pins the Displacement Efficiency formula to the mobile-fluid-phase standard:

    Ed = (1 - Swi - Sor) / (1 - Swi)

and guards against a regression to the WRONG form (Swi - Sor) / Swi.

This pins the SINGLE source-of-truth function rather than trapping a magic
output value at runtime — 47.6% is a perfectly valid CORRECT result for some
Swi/Sor pairs, so a runtime "fail on 47.6%" check would reject good data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import calculate_derived_value


def _ed(swi: float, sor: float) -> float:
    return calculate_derived_value("displacement_efficiency", f"swi={swi},sor={sor}", "t")


def test_ed_uses_mobile_phase_formula():
    # PRC reference sample: Swi=0.42, Sor=0.22 -> 62.1%
    assert round(_ed(0.42, 0.22), 3) == 0.621
    # The wrong form (Swi - Sor)/Swi would give 0.476 for these inputs.
    assert round(_ed(0.42, 0.22), 3) != 0.476


def test_ed_matches_closed_form_across_inputs():
    for swi, sor in [(0.25, 0.393), (0.30, 0.20), (0.15, 0.35), (0.50, 0.10)]:
        expected = (1.0 - swi - sor) / (1.0 - swi)
        assert abs(_ed(swi, sor) - expected) < 1e-9


def test_476_percent_is_a_valid_correct_result_not_an_error():
    # Swi=0.25, Sor=0.393 yields 47.6% via the CORRECT formula — proving a
    # runtime tripwire on the value 0.476 would flag legitimate data.
    assert round(_ed(0.25, 0.393), 3) == 0.476


def test_ed_accepts_percent_scaled_inputs():
    # The function divides by 100 when inputs look like percentages.
    assert abs(_ed(42.0, 22.0) - _ed(0.42, 0.22)) < 1e-9
