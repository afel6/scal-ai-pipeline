"""D2.2 scenario — a fitted value inside a markdown table cell (A4 defect 2).

The gate's original separator knew prose only ("n is 1.98", "n = 1.98") and was
blind to the exact table format the system prompt mandates
("| Archie Saturation Exponent (n) | 1.987 |"), so a fabricated value in a table
cell survived while the same value in prose was stripped. Replayed offline
through the real chat loop: the cache-path RI fit refuses (true n = 1.2), the
scripted model answers ONLY in table form, and every cell value must become an
explicit unverified marker without breaking the row shape. A control run with a
successful fit (n = 1.85) proves a CORRECT table value is not collateral damage.
"""
import json
import re

import pytest

import app
from scenario_support import FIXTURES, clear_session, run_scenario

SID = "d2-table_cell_fitted_value"
SID_OK = "d2-table_cell_fitted_value-success"
QUESTION = "Report the Archie saturation exponent n fitted from the RI data for sample D2-1 as a table."
MARKER = "[unverified - no successful fit produced this value]"
PRE_A4_SEPARATOR = "(?:is|=|:)"          # the prose-only separator the A4 fix replaced
CURRENT_SEPARATOR = r"(?:is|=|:|\|)"


def _scripted_rows(name: str):
    """The table rows the scripted model emitted (from the fixture, never inline)."""
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    text = data["steps"][-1]["assistant"]["text"]
    return [ln for ln in text.splitlines() if ln.startswith("|") and not ln.startswith("|---")]


def _reply_rows(reply: str):
    return [ln for ln in reply.splitlines() if ln.startswith("|") and not ln.startswith("|---")]


def _cells(row: str):
    return [c.strip() for c in row.strip().strip("|").split("|")]


@pytest.fixture(autouse=True)
def _clean():
    for sid in (SID, SID_OK):
        clear_session(sid)
    yield
    for sid in (SID, SID_OK):
        clear_session(sid)


def test_every_table_cell_value_is_stripped_and_row_shapes_survive(caplog):
    with caplog.at_level("WARNING"):
        run = run_scenario("table_cell_fitted_value", sid=SID, question=QUESTION, n=1.2)
    fits = run.calls("fit_petrophysical_curve")
    assert fits and fits[-1]["status"] == "error" and fits[-1]["values"] == {}
    # The model was told the fit FAILED before it wrote the table.
    content = run.tool_messages(1)[0]["content"]
    assert '"status": "error"' in content and "TOOL FAILURE" in content, content

    reply = run.reply
    assert "1.987" not in reply, reply
    scripted, got = _scripted_rows("table_cell_fitted_value"), _reply_rows(reply)
    assert len(got) == len(scripted) == 4, reply          # header + the 3 cell variants
    for before, after in zip(scripted, got):
        assert after.count("|") == before.count("|"), (before, after)
    # Every value cell (all three variants: plain, **bold**, backtick param) is the marker.
    for row in got[1:]:
        assert _cells(row)[1] == MARKER, row
    assert reply.count(MARKER) == 3, reply
    assert not re.search(r"\|\s*\*{0,2}\d+\.\d+\*{0,2}\s*\|", reply), reply   # no bare number cell left
    assert any("citation gate" in r.message.lower() and "1.987" in r.message for r in caplog.records)


def test_correct_table_value_survives_a_successful_fit():
    run = run_scenario("table_cell_fitted_value_success", sid=SID_OK, question=QUESTION, n=1.85)
    fits = run.calls("fit_petrophysical_curve")
    assert fits and fits[-1]["status"] == "success"
    assert abs(fits[-1]["values"]["n"] - 1.85) <= 0.006, fits[-1]
    rows = _reply_rows(run.reply)
    value_rows = [r for r in rows if _cells(r)[0] == "Archie Saturation Exponent n"]
    assert value_rows and _cells(value_rows[0])[1] == "1.850", run.reply
    assert "[unverified" not in run.reply, run.reply


def test_same_scenario_is_deterministic_across_runs():
    a = run_scenario("table_cell_fitted_value", sid=SID, question=QUESTION, n=1.2).reply
    clear_session(SID)
    b = run_scenario("table_cell_fitted_value", sid=SID, question=QUESTION, n=1.2).reply
    assert a == b


def test_without_the_gate_the_table_value_reaches_the_user(monkeypatch):
    """The defect, reproduced: with the gate bypassed, every cell keeps 1.987."""
    monkeypatch.setattr(app, "enforce_citation_gate", lambda text, sid: text)
    run = run_scenario("table_cell_fitted_value", sid=SID, question=QUESTION, n=1.2)
    assert run.calls("fit_petrophysical_curve")[-1]["status"] == "error"
    assert run.reply.count("1.987") == 3 and MARKER not in run.reply, run.reply


def test_with_the_pre_a4_prose_only_separator_the_table_cell_survives(monkeypatch):
    """The historically precise defect: the same gate with the original
    separator (is|=|:) — no '|' — lets the table cells through while the same
    value in prose is stripped. Proof the '|' separator is load-bearing."""
    assert CURRENT_SEPARATOR in app._GATE_RE.pattern
    pre_a4 = re.compile(app._GATE_RE.pattern.replace(CURRENT_SEPARATOR, PRE_A4_SEPARATOR),
                        app._GATE_RE.flags)
    assert pre_a4.pattern != app._GATE_RE.pattern
    monkeypatch.setattr(app, "_GATE_RE", pre_a4)
    run = run_scenario("table_cell_fitted_value", sid=SID, question=QUESTION, n=1.2)
    assert run.calls("fit_petrophysical_curve")[-1]["status"] == "error"
    assert run.reply.count("1.987") == 3 and MARKER not in run.reply, run.reply
    # Same ledger, same patched gate, prose form: stripped.
    prose = app.enforce_citation_gate("The fitted exponent n is 1.987 for D2-1.", SID)
    assert "1.987" not in prose and MARKER in prose, prose
