"""D2.2 scenario — the plot payload survives the gate byte-for-byte (A4 defect 3).

A `__PRC_PLOT__` payload is machine-read chart JSON. Its curve label
("RI Archie  n=1.850") and metadata ("archie": {"n": 1.85}) carry exactly the
cue + parameter + number shape the citation gate hunts, so an unmasked gate
rewrites INSIDE the JSON and corrupts the chart. The gate masks payloads via
`_PLOT_BLOCK_RE` before gating (and the ledger reads the fitted value through
the same regex). Here the cache-path RI fit SUCCEEDS (true n = 1.85) and the
scripted model restates a wrong value in prose (n = 1.999): the prose value
must be stripped, the payload the tool rendered must reach the caller unchanged.
"""
import json
import re

import pytest

import app
from scenario_support import clear_session, run_scenario

SID = "d2-plot_payload_survives"
QUESTION = "Fit the Archie saturation exponent n from the RI data for sample D2-1 and show the plot."
MARKER = "[unverified - value differs from the fitted result]"
NO_FIT_MARKER = "[unverified - no successful fit produced this value]"
LABEL = "RI Archie  n=1.850"
NEVER = re.compile(r"(?!x)x")            # a mask that masks nothing


@pytest.fixture(autouse=True)
def _clean():
    clear_session(SID)
    yield
    clear_session(SID)


@pytest.fixture
def rendered(monkeypatch):
    """Records every string `_format_tool_response` returned (the tool's own
    render, ledger recording included), without altering it."""
    out = []
    orig = app.assistant._format_tool_response

    def spy(name, args, result):
        formatted = orig(name, args, result)
        out.append(formatted)
        return formatted

    monkeypatch.setattr(app.assistant, "_format_tool_response", spy)
    return out


def _payloads(text):
    return [m.group(0) for m in app._PLOT_BLOCK_RE.finditer(text)]


def _json_of(block):
    return json.loads(block.split("__PRC_PLOT__", 1)[1].strip())


def test_prose_value_is_stripped_but_the_payload_is_untouched(rendered):
    run = run_scenario("plot_payload_survives", sid=SID, question=QUESTION, n=1.85)
    fits = run.calls("fit_petrophysical_curve")
    assert fits and fits[-1]["status"] == "success"
    assert fits[-1]["values"]["n"] == pytest.approx(1.85, abs=1e-4)
    # The tool rendered exactly one plot.
    assert len(rendered) == 1 and rendered[0].startswith("__PRC_PLOT__"), rendered
    tool_block = _payloads(rendered[0])
    assert len(tool_block) == 1

    reply = run.reply
    # Prose: the wrong restatement is gone, the marker stands, once.
    assert "1.999" not in reply
    assert reply.count(MARKER) == 1, reply
    assert re.search(r"exponent n = \[unverified - value differs", reply), reply
    # Payload: present exactly once, parses, still says what the tool said.
    blocks = _payloads(reply)
    assert len(blocks) == 1 and reply.count("__PRC_PLOT__") == 1
    data = _json_of(blocks[0])
    assert data["metadata"]["archie"]["n"] == pytest.approx(1.85, abs=1e-4)
    assert data["curves"][1]["name"] == LABEL
    # Byte-identical to what the tool rendered.
    assert blocks[0].strip() == tool_block[0].strip()
    assert rendered[0].strip() in reply


def test_same_scenario_is_deterministic_across_runs():
    a = run_scenario("plot_payload_survives", sid=SID, question=QUESTION, n=1.85).reply
    clear_session(SID)
    b = run_scenario("plot_payload_survives", sid=SID, question=QUESTION, n=1.85).reply
    assert a == b


def test_without_the_plot_regex_the_fabrication_reaches_the_user(rendered, monkeypatch):
    """The defect, reproduced through the real loop: with `_PLOT_BLOCK_RE`
    unable to find a payload, the ledger reads no fitted value from the tool's
    render, the gate has nothing to compare 1.999 against, and the wrong
    number rides the successful call straight to the user."""
    monkeypatch.setattr(app, "_PLOT_BLOCK_RE", NEVER)
    run = run_scenario("plot_payload_survives", sid=SID, question=QUESTION, n=1.85)
    fit = run.calls("fit_petrophysical_curve")[-1]
    assert fit["status"] == "success" and fit["values"] == {}
    assert "1.999" in run.reply and MARKER not in run.reply
    assert rendered[0].strip() in run.reply


def test_without_the_mask_the_gate_rewrites_inside_the_chart_json(rendered):
    """The masking itself, proven load-bearing on the real reply: a payload the
    ledger does not back (a sandbox fitter's plot, or a row that was never
    recorded) is rewritten INSIDE the JSON by an unmasked gate — the metadata
    number becomes a bracketed marker and the chart no longer parses. With the
    mask on, the same unbacked payload comes through byte-for-byte."""
    run = run_scenario("plot_payload_survives", sid=SID, question=QUESTION, n=1.85)
    payload = _payloads(run.reply)[0]
    app.reset_tool_call_ledger(SID)            # nothing backs the payload's numbers any more
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(app, "_PLOT_BLOCK_RE", NEVER)
        corrupted = app.enforce_citation_gate(run.reply, SID)
    assert payload not in corrupted
    assert LABEL not in corrupted and NO_FIT_MARKER in corrupted
    with pytest.raises(json.JSONDecodeError):
        _json_of(corrupted.split("\n\n## ", 1)[0])
    # Same evidence state, mask on: the payload is intact (the prose value was
    # already a marker, so the gated reply is unchanged).
    masked = app.enforce_citation_gate(run.reply, SID)
    assert masked == run.reply and _payloads(masked) == [payload]
    assert _json_of(payload)["curves"][1]["name"] == LABEL
