"""C2 gate finding — a reported fitted value must EQUAL the fitted result.

The A2 protocol on gemini-2.5-flash surfaced this: the RI fit succeeded and
returned n = 1.850 (plot label + metadata), yet the model wrote n = 1.999 /
1.99 / 1.871 in 4 of 5 runs — and the citation gate passed them, because it
only checked that a successful call to the allowed tool existed. Existence by
tool name is not evidence for a number. Now the ledger records the values a
successful fit produced and the gate strips any result-shaped value that
matches none of them (within rounding tolerance).
"""
import json

import pytest

import app

SID = "c2-gate-values"


@pytest.fixture(autouse=True)
def _clean():
    app.reset_tool_call_ledger(SID)
    yield
    app.reset_tool_call_ledger(SID)


def test_mismatched_value_is_stripped_even_after_a_successful_call():
    app.record_tool_call(SID, "fit_petrophysical_curve", "success", {"model": "ri"},
                         ["n"], values={"n": 1.85})
    gated = app.enforce_citation_gate("The fitted saturation exponent n is 1.999.", SID)
    assert "1.999" not in gated and "[unverified" in gated


def test_matching_value_survives_with_rounding():
    app.record_tool_call(SID, "fit_petrophysical_curve", "success", {"model": "ri"},
                         ["n"], values={"n": 1.85})
    for txt in ("n = 1.850", "the exponent n is 1.85", "| Archie Saturation Exponent n | 1.850 | - |"):
        assert app.enforce_citation_gate(txt, SID) == txt


def test_mismatch_in_markdown_table_cell_is_stripped():
    app.record_tool_call(SID, "fit_petrophysical_curve", "success", {"model": "ri"},
                         ["n"], values={"n": 1.85})
    gated = app.enforce_citation_gate("| Archie Saturation Exponent n | 1.999 | - |", SID)
    assert "1.999" not in gated and "[unverified" in gated


def test_existence_only_when_no_values_were_recorded():
    # Older/other tools may not expose fitted values; keep A4's existence check.
    app.record_tool_call(SID, "fit_petrophysical_curve", "success", {"model": "ri"}, ["n"])
    txt = "The fitted saturation exponent n is 1.999."
    assert app.enforce_citation_gate(txt, SID) == txt


def test_failed_tool_named_in_a_source_cell_is_dropped():
    """D2 corpus finding: the bracketed citation of a failed call was dropped,
    but the same tool named in the mandated table's Source cell survived next
    to the unverified marker — a citation in another format."""
    app.record_tool_call(SID, "fit_petrophysical_curve", "error", {"model": "ri"}, [])
    gated = app.enforce_citation_gate(
        "| Archie Saturation Exponent n | 1.987 | fit_petrophysical_curve |", SID)
    assert "1.987" not in gated and "fit_petrophysical_curve" not in gated
    assert "[no successful call]" in gated
    assert gated.count("|") == 4                      # the row shape is preserved


def test_mismatch_is_logged(caplog):
    app.record_tool_call(SID, "fit_petrophysical_curve", "success", {}, ["n"], values={"n": 1.85})
    with caplog.at_level("WARNING"):
        app.enforce_citation_gate("the fitted exponent n = 1.999", SID)
    assert any("citation gate" in r.message.lower() and "1.999" in r.message for r in caplog.records)


def test_formatter_records_fitted_values_from_the_plot_payload():
    """The ledger row for a successful fit carries the values the tool produced,
    read from the plot metadata the formatter emits."""
    from physics_sandbox import PhysicsSandbox
    sw = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]
    ri = [round(s ** -2.0, 5) for s in sw]                      # clean fit, n = 2.0
    fit = PhysicsSandbox().fit_archie(sw, ri, "RI")
    app._tls.current_session_id = SID
    app.assistant._format_tool_response("sandbox_fit_archie",
                                        {"model_type": "RI", "sample_name": "v"}, json.dumps(fit))
    rows = app.get_tool_call_records(SID)
    assert rows and rows[-1]["status"] == "success"
    assert rows[-1]["values"]["n"] == pytest.approx(2.0, abs=1e-3)
