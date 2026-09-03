"""D2.2 scenario — the tool-call ledger is per-session evidence (C2 item 1.1).

Defect: rows were recorded under the shared "" bucket and a gate consulted
with an empty sid read that same bucket, so a stale success by tool name from
ANOTHER conversation silently backed a fabricated value (silent pass-through).

Replayed offline through the real chat loop: session A's RI fit succeeds
(true n = 1.85) and its restated 1.850 survives; session B restates the same
1.850 with no fit of its own — A's matching success must not back it. At the
gate level an empty sid must fail closed (no evidence -> strip).
"""
import pytest

import app
from scenario_support import clear_session, run_scenario

SID_A = "d2-ledger_sid_mismatch-A"
SID_B = "d2-ledger_sid_mismatch-B"
QUESTION = "Report the fitted Archie saturation exponent n from the RI data for sample D2-1."
CLAIM = "n = 1.850"
NO_FIT = "[unverified - no successful fit produced this value]"


@pytest.fixture(autouse=True)
def _clean():
    for sid in (SID_A, SID_B):
        clear_session(sid)
    yield
    for sid in (SID_A, SID_B):
        clear_session(sid)


def _run_a():
    run = run_scenario("ledger_sid_mismatch", sid=SID_A, question=QUESTION, n=1.85)
    fits = run.calls("fit_petrophysical_curve")
    assert fits and fits[-1]["status"] == "success", fits
    assert abs(fits[-1]["values"]["n"] - 1.85) <= 0.006, fits[-1]
    return run


def test_own_session_success_backs_the_value():
    run = _run_a()
    assert CLAIM in run.reply and "[unverified" not in run.reply, run.reply


def test_success_in_another_session_does_not_back_the_value(caplog):
    run_a = _run_a()
    with caplog.at_level("WARNING"):
        run_b = run_scenario("ledger_sid_mismatch_no_call", sid=SID_B, question=QUESTION, n=1.85)
    # Evidence does not cross sessions: 1.850 is stripped in B, intact in A.
    assert "1.850" not in run_b.reply, run_b.reply
    assert NO_FIT in run_b.reply, run_b.reply
    assert CLAIM in run_a.reply
    # B made no tool call of its own; A's ledger still holds the matching success.
    assert run_b.calls("fit_petrophysical_curve") == []
    assert app.get_tool_call_records(SID_A) == run_a.ledger
    assert app.get_tool_call_records(SID_A)[-1]["values"] == run_a.ledger[-1]["values"]
    assert any("citation gate" in r.message.lower() and "1.850" in r.message
               and SID_B in r.message for r in caplog.records)


def test_empty_sid_fails_closed_at_the_gate():
    run_a = _run_a()
    assert app.get_tool_call_records("") == []
    # The same text that survived in A, consulted with no session: no evidence.
    gated = app.enforce_citation_gate(run_a.reply, "")
    assert CLAIM not in gated and NO_FIT in gated, gated
    # The plot payload (label "RI Archie  n=1.850") is machine-read JSON and is
    # masked, never rewritten — only the prose claim is stripped.
    assert app._PLOT_BLOCK_RE.findall(gated) == app._PLOT_BLOCK_RE.findall(run_a.reply)
    assert len(app._PLOT_BLOCK_RE.findall(gated)) == 1
    # And with A's own sid it still survives — the sid is the whole difference.
    assert app.enforce_citation_gate(run_a.reply, SID_A) == run_a.reply


def test_same_scenarios_are_deterministic_across_runs():
    a1 = _run_a().reply
    b1 = run_scenario("ledger_sid_mismatch_no_call", sid=SID_B, question=QUESTION, n=1.85).reply
    clear_session(SID_A)
    clear_session(SID_B)
    a2 = _run_a().reply
    b2 = run_scenario("ledger_sid_mismatch_no_call", sid=SID_B, question=QUESTION, n=1.85).reply
    assert (a1, b1) == (a2, b2)


def test_without_per_session_binding_the_foreign_success_would_back_the_value(monkeypatch):
    """The defect, reproduced: the old shared-bucket lookup — a ledger read that
    ignores the sid and returns whatever success exists — lets A's fit back
    B's fabricated 1.850. Proof that per-session binding is load-bearing."""
    a_rows = _run_a().ledger
    monkeypatch.setattr(app, "get_tool_call_records", lambda sid: list(a_rows))
    run_b = run_scenario("ledger_sid_mismatch_no_call", sid=SID_B, question=QUESTION, n=1.85)
    assert CLAIM in run_b.reply and NO_FIT not in run_b.reply, run_b.reply
