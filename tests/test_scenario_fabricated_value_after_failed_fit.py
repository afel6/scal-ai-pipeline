"""D2.2 scenario — a tool call fails, then a value cites it (the 1.987 fabrication).

A4 defect 1, now replayed offline through the real chat loop: the cache-path
RI fit refuses (true n = 1.2 is outside [1.5, 3.0]), the scripted model reports
`n = 1.987 [fit_petrophysical_curve, model=ri]` anyway, in prose AND in the
mandated table cell. The citation gate — at answer assembly — must strip both
numbers and the citation, leaving explicit unverified markers.
"""
import re

import pytest

import app
from scenario_support import clear_session, run_scenario

SID = "d2-fabricated-1987"
QUESTION = "Report the Archie saturation exponent n fitted from the RI data for sample B0-7."
MARKER = "[unverified - no successful fit produced this value]"


@pytest.fixture(autouse=True)
def _clean():
    clear_session(SID)
    yield
    clear_session(SID)


def test_fit_fails_and_the_cited_value_is_stripped_everywhere(caplog):
    with caplog.at_level("WARNING"):
        run = run_scenario("fabricated_value_after_failed_fit", sid=SID, question=QUESTION, n=1.2)
    # The real tool ran on the seeded cache and refused (ledger row: error).
    fits = run.calls("fit_petrophysical_curve")
    assert fits and fits[-1]["status"] == "error" and fits[-1]["values"] == {}
    # The model was told a FAILURE before it wrote 1.987 — not "plot computed,
    # state Archie n" (the loop used to report the analytic models' refusal as
    # success because the fit runs inside the formatter).
    tool_msgs = run.tool_messages(1)
    assert tool_msgs, run.transcript[1]
    content = tool_msgs[0]["content"]
    assert '"status": "error"' in content and "TOOL FAILURE" in content, content
    assert "computed" not in content and "1.987" not in content
    # Assembly: the fabricated value is gone from prose and table; markers stand.
    assert "1.987" not in run.reply
    assert run.reply.count(MARKER) == 2, run.reply
    assert "fit_petrophysical_curve" not in run.reply          # the citation of a failed call is dropped
    assert not re.search(r"\bn\b[^.\n|]{0,60}(?:is|=|\|)\s*\*{0,2}\d", run.reply)
    assert any("citation gate" in r.message.lower() and "1.987" in r.message for r in caplog.records)


def test_same_scenario_is_deterministic_across_runs():
    a = run_scenario("fabricated_value_after_failed_fit", sid=SID, question=QUESTION, n=1.2).reply
    clear_session(SID)
    b = run_scenario("fabricated_value_after_failed_fit", sid=SID, question=QUESTION, n=1.2).reply
    assert a == b


def test_without_the_gate_the_fabrication_would_reach_the_user(monkeypatch):
    """The defect, reproduced: with the gate bypassed, 1.987 rides the failed
    call straight to the user. Proof the scenario exercises the guard."""
    monkeypatch.setattr(app, "enforce_citation_gate", lambda text, sid: text)
    run = run_scenario("fabricated_value_after_failed_fit", sid=SID, question=QUESTION, n=1.2)
    assert run.calls("fit_petrophysical_curve")[-1]["status"] == "error"
    assert "1.987" in run.reply and MARKER not in run.reply
