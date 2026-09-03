"""D2.2 scenario — the model retries around a refusal through the sandbox (C1: 2 of 13).

Defect: the cache-path RI fit refuses (true n = 1.2 is outside [1.5, 3.0]);
the model then calls `sandbox_fit_archie` with its own arrays. The sandbox
clamps the out-of-range free fit onto the bound (n = 1.500, corrected=True)
and the formatter used to label the curve "RI Archie n=1.500" as if fitted,
while the prose reported "the fitted exponent n = 1.500".

Two independent guards now hold: the formatter labels a corrected fit
"not fitted" (metadata.archie.n = null), and the citation gate strips the
prose number because the sandbox is NOT a cache-backed fitter — a successful
sandbox call proves the arithmetic ran, not that the number came from the lab.
"""
import json

import pytest

import app
import physics_sandbox
from scenario_support import SW, clear_session, ri_series, run_scenario

SID = "d2-sandbox_after_refusal"
QUESTION = "Fit the Archie saturation exponent n from the RI data for sample D2-1."
MARKER = "[unverified - no successful fit produced this value]"
SANDBOX_EVIDENCE = frozenset({"fit_petrophysical_curve", "sandbox_fit_archie"})


@pytest.fixture(autouse=True)
def _clean():
    clear_session(SID)
    yield
    clear_session(SID)


def _plots(reply):
    return [json.loads(m.group(0).split("__PRC_PLOT__", 1)[1])
            for m in app._PLOT_BLOCK_RE.finditer(reply)]


def _prose(reply):
    return app._PLOT_BLOCK_RE.sub("", reply)


def test_fixture_arrays_are_the_seeded_series():
    script = json.loads((__import__("scenario_support").FIXTURES / "sandbox_after_refusal.json").read_text("utf-8"))
    args = script["steps"][1]["assistant"]["tool_calls"][0]["args"]
    assert args["x"] == SW and args["y"] == ri_series(1.2)


def test_sandbox_retry_after_refusal_is_not_presented_as_a_fit():
    run = run_scenario("sandbox_after_refusal", sid=SID, question=QUESTION, n=1.2)
    # Ledger: the cache-path fit refused; the sandbox ran but recorded NO value.
    fits = run.calls("fit_petrophysical_curve")
    assert fits and fits[-1]["status"] == "error" and fits[-1]["values"] == {}
    sb = run.calls("sandbox_fit_archie")
    assert sb and sb[-1]["status"] == "success" and sb[-1]["values"] == {}
    # The model was told the first tool FAILED before it went to the sandbox.
    content = run.tool_messages(1)[0]["content"]
    assert '"status": "error"' in content and "TOOL FAILURE" in content, content
    # Formatter guard: the clamped sandbox fit is labelled unresolved, never n=1.500.
    plots = _plots(run.reply)
    assert len(plots) == 1, run.reply
    names = [c["name"] for c in plots[0]["curves"]]
    assert any("not fitted" in nm for nm in names), names
    assert not any(app.re.search(r"n=\d", nm) for nm in names), names
    archie = plots[0]["metadata"]["archie"]
    assert archie["fitted"] is False and archie["n"] is None, archie
    # Citation gate: the sandbox is not evidence for a number — 1.500 is stripped.
    prose = _prose(run.reply)
    assert "1.500" not in prose and MARKER in prose, prose


def test_same_scenario_is_deterministic_across_runs():
    a = run_scenario("sandbox_after_refusal", sid=SID, question=QUESTION, n=1.2).reply
    clear_session(SID)
    b = run_scenario("sandbox_after_refusal", sid=SID, question=QUESTION, n=1.2).reply
    assert a == b


def test_if_the_sandbox_counted_as_evidence_the_clamped_value_would_reach_the_user(monkeypatch):
    """The defect, reproduced: admit `sandbox_fit_archie` to the evidence
    allow-list (the "sandbox counts" mistake) and the successful-but-valueless
    sandbox row backs the prose 1.500. Proof the allow-list is load-bearing."""
    for key in list(app._GATED_PARAMETERS):
        monkeypatch.setitem(app._GATED_PARAMETERS, key, SANDBOX_EVIDENCE)
    run = run_scenario("sandbox_after_refusal", sid=SID, question=QUESTION, n=1.2)
    assert run.calls("fit_petrophysical_curve")[-1]["status"] == "error"
    assert run.calls("sandbox_fit_archie")[-1]["status"] == "success"
    prose = _prose(run.reply)
    assert "1.500" in prose and MARKER not in prose, prose


def test_the_plot_label_depends_on_the_corrected_flag(monkeypatch):
    """Formatter counterpart: the same clamped result with corrected=False
    renders "RI Archie n=1.500" and records n in the ledger — the label guard
    lives entirely on the sandbox's `corrected` flag. The citation gate still
    strips the prose, because the sandbox is not a cache-backed fitter."""
    original = physics_sandbox.PhysicsSandbox.fit_archie

    def _uncorrected(self, x, y, model_type="RI"):
        res = original(self, x, y, model_type)
        res["corrected"] = False
        return res

    monkeypatch.setattr(physics_sandbox.PhysicsSandbox, "fit_archie", _uncorrected)
    run = run_scenario("sandbox_after_refusal", sid=SID, question=QUESTION, n=1.2)
    plots = _plots(run.reply)
    names = [c["name"] for c in plots[0]["curves"]]
    assert any("n=1.500" in nm for nm in names) and not any("not fitted" in nm for nm in names), names
    archie = plots[0]["metadata"]["archie"]
    assert archie["fitted"] is True and archie["n"] == pytest.approx(1.5)
    assert run.calls("sandbox_fit_archie")[-1]["values"] == pytest.approx({"n": 1.5})
    prose = _prose(run.reply)
    assert "1.500" not in prose and MARKER in prose, prose
