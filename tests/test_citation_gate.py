"""A reported fitted parameter must map to a successful tool call (finding A4).

Observed: with the RI fit failing, the model reported `n = 1.987` and cited
`[fit_petrophysical_curve, model=ri]` — a call that had returned an error. The
prompt already forbids this ("If the tool fails, report the failure - do not
estimate"), so the gap is enforcement, not instruction. These tests pin the
enforcement in code.
"""

import pytest

import app


SID = "a4-gate"


@pytest.fixture(autouse=True)
def clean_ledger() -> None:
    app.reset_tool_call_ledger(SID)
    yield
    app.reset_tool_call_ledger(SID)


def test_ledger_records_a_successful_call() -> None:
    call_id = app.record_tool_call(SID, "fit_petrophysical_curve", "success",
                                   {"model": "ri"}, ["n"])
    records = app.get_tool_call_records(SID)
    assert len(records) == 1
    assert records[0]["call_id"] == call_id
    assert records[0]["tool"] == "fit_petrophysical_curve"
    assert records[0]["status"] == "success"
    assert records[0]["parameters"] == ["n"]


def test_ledger_records_a_failed_call() -> None:
    app.record_tool_call(SID, "fit_petrophysical_curve", "error", {"model": "ri"}, [])
    assert app.get_tool_call_records(SID)[0]["status"] == "error"


def test_number_is_stripped_when_the_cited_tool_failed() -> None:
    """The exact observed failure: n reported off a failed fit."""
    app.record_tool_call(SID, "fit_petrophysical_curve", "error", {"model": "ri"}, [])
    text = "The Archie saturation exponent `n` for Sample K7-12 is **1.987** [fit_petrophysical_curve, model=ri]."
    gated = app.enforce_citation_gate(text, SID)
    assert "1.987" not in gated
    assert "fit_petrophysical_curve" not in gated
    assert "unverified" in gated.lower()


def test_number_survives_when_the_tool_succeeded() -> None:
    app.record_tool_call(SID, "fit_petrophysical_curve", "success",
                         {"model": "ri"}, ["n"])
    text = "The Archie saturation exponent n is 1.850 [fit_petrophysical_curve, model=ri]."
    gated = app.enforce_citation_gate(text, SID)
    assert "1.850" in gated
    assert "unverified" not in gated.lower()


def test_number_is_stripped_when_no_call_was_made_at_all() -> None:
    text = "The Archie saturation exponent n is 2.140."
    gated = app.enforce_citation_gate(text, SID)
    assert "2.140" not in gated
    assert "unverified" in gated.lower()


def test_rejections_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    app.record_tool_call(SID, "fit_petrophysical_curve", "error", {"model": "ri"}, [])
    text = "The saturation exponent n is 1.987."
    with caplog.at_level("WARNING"):
        app.enforce_citation_gate(text, SID)
    assert any("citation gate" in r.message.lower() for r in caplog.records), \
        "a stripped parameter must leave a log line"


def test_prose_without_fitted_parameters_is_untouched() -> None:
    text = "The sample is strongly water-wet with an Amott-Harvey index of 0.72."
    assert app.enforce_citation_gate(text, SID) == text


@pytest.mark.parametrize("parameter", ["n", "m", "a", "nw", "no"])
def test_every_gated_parameter_is_covered(parameter: str) -> None:
    text = f"The fitted {parameter} is 2.345."
    gated = app.enforce_citation_gate(text, SID)
    assert "2.345" not in gated, f"{parameter} was not gated"
