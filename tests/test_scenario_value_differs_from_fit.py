"""D2.2 scenario — the fit succeeded, the model restated a different number.

C2 gate finding (A2 protocol on gemini-2.5-flash): the cache-path RI fit
succeeded and returned n = 1.850, yet the model wrote 1.999 / 1.99 / 1.871 in
4 of 5 live runs — and the old gate passed them, because it only checked that a
successful call to the allowed tool existed. Existence of a successful call is
not evidence for a number. The ledger row now carries the values the fit
produced and the gate strips a restated number that matches none of them
(tolerance max(0.006, 0.5%)), leaving correct restatements and the plot
payload untouched.
"""
import json

import pytest

import app
from scenario_support import clear_session, run_scenario

SID = "d2-value_differs_from_fit"
QUESTION = "Report the Archie saturation exponent n fitted from the RI data for sample D2-1."
DIFFERS = "[unverified - value differs from the fitted result]"
NO_FIT = "[unverified - no successful fit produced this value]"


@pytest.fixture(autouse=True)
def _clean():
    clear_session(SID)
    yield
    clear_session(SID)


def _plot_metadata(reply: str) -> dict:
    blocks = [m.group(0) for m in app._PLOT_BLOCK_RE.finditer(reply)]
    assert blocks, reply
    return json.loads(blocks[0].split("__PRC_PLOT__", 1)[1].strip())["metadata"]


def test_restated_values_that_differ_from_the_fit_are_stripped_and_correct_ones_survive(caplog):
    with caplog.at_level("WARNING"):
        run = run_scenario("value_differs_from_fit", sid=SID, question=QUESTION, n=1.85)
    # The real tool ran on the seeded cache, succeeded, and recorded WHAT it fitted.
    fits = run.calls("fit_petrophysical_curve")
    assert fits and fits[-1]["status"] == "success", fits
    assert fits[-1]["values"]["n"] == pytest.approx(1.85, abs=1e-3), fits[-1]
    reply = run.reply
    # The two drifted restatements are gone — prose (1.999) and table cell (1.871).
    assert "1.999" not in reply and "1.871" not in reply, reply
    assert reply.count(DIFFERS) == 2, reply
    assert NO_FIT not in reply
    # The correct restatement and its rounded form survive (within tolerance).
    assert "n = 1.850" in reply and "n is 1.85" in reply, reply
    assert "[unverified - value differs from the fitted result] for Sample" not in reply
    # The plot payload is never rewritten: its metadata still carries the fit.
    meta = _plot_metadata(reply)
    assert meta["archie"]["n"] == pytest.approx(1.85, abs=1e-3), meta
    assert "n=1.850" in reply                                    # the curve label
    # Each rejection is logged with the fitted value it was checked against.
    strip_logs = [r.message for r in caplog.records if "citation gate" in r.message.lower()]
    assert any("1.999" in m and "1.85" in m for m in strip_logs), strip_logs
    assert any("1.871" in m for m in strip_logs), strip_logs


def test_tolerance_boundary_just_inside_survives_just_outside_is_stripped():
    run = run_scenario("value_differs_from_fit_boundary", sid=SID, question=QUESTION, n=1.85)
    fitted = run.calls("fit_petrophysical_curve")[-1]["values"]["n"]
    tol = max(0.006, 0.005 * fitted)
    assert abs(1.855 - fitted) <= tol < abs(1.870 - fitted)      # the fixture sits astride the tolerance
    reply = run.reply
    assert "n = 1.855" in reply, reply
    assert "1.870" not in reply and reply.count(DIFFERS) == 1, reply


def test_same_scenario_is_deterministic_across_runs():
    a = run_scenario("value_differs_from_fit", sid=SID, question=QUESTION, n=1.85).reply
    clear_session(SID)
    b = run_scenario("value_differs_from_fit", sid=SID, question=QUESTION, n=1.85).reply
    assert a == b


def test_without_value_binding_the_drifted_number_would_reach_the_user(monkeypatch):
    """The defect, reproduced: with the ledger back to pre-C2 existence-only rows
    (no fitted values recorded), 1.999 rides the successful call straight to
    the user. Proof that value-binding is the load-bearing half of the gate."""
    monkeypatch.setattr(app, "_extract_fitted_values", lambda formatted: {})
    run = run_scenario("value_differs_from_fit", sid=SID, question=QUESTION, n=1.85)
    fit = run.calls("fit_petrophysical_curve")[-1]
    assert fit["status"] == "success" and fit["values"] == {}
    assert "1.999" in run.reply and "1.871" in run.reply and DIFFERS not in run.reply
