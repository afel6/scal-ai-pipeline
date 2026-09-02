"""D2.3 — the full scal stack end to end on the scripted mock, zero network.

One scripted conversation drives: tool dispatch through answer assembly (a
cache-path RI fit, a sandbox retry on out-of-range data, an executive report);
the citation gate with value-binding and the \\b-bounded parameter match; A3
provenance (the Brooks-Corey notice in the transcript reaches the generated
.docx); plot provenance (the clamped sandbox fit renders unfitted); and
provenance-token resolution. The egress guard must record zero attempts over
the whole run and the adapter must still be the keyless mock.
"""
import json
import re

import pytest
from docx import Document

import app
import egress_guard
import prc_physics
from scenario_support import WETTABILITY, clear_session, run_scenario

SID = "d2-full-stack"
QUESTION = "Analyze sample D2-1: fit the RI data, retry in the sandbox, generate the executive report, and summarize."


def _rows_without_endpoints():
    return [
        {"Water_Saturation_fraction": 1.0, "Capillary_Pressure_psi": 10.0,
         "Relative_Permeability_Water": 0.10, "Relative_Permeability_Oil": 0.20},
        {"Water_Saturation_fraction": 1.0, "Capillary_Pressure_psi": 20.0,
         "Relative_Permeability_Water": 0.20, "Relative_Permeability_Oil": 0.10},
    ]


@pytest.fixture
def stack(tmp_path, monkeypatch):
    clear_session(SID)
    monkeypatch.setattr(app, "PRC_VAULT", tmp_path)          # the report lands here
    # The upload path stores the A3 notice as a model turn; the report engine
    # renders any such turn into "2.1 Parameter Provenance".
    notice = prc_physics.provenance_notice(prc_physics.fit_brooks_corey(_rows_without_endpoints()))
    app.db("INSERT INTO m (sid, role, text, ts, user_email) VALUES (?,?,?,?,?)",
           (SID, "model", notice, 1.0, "test@prc.local"))
    before = len(egress_guard.ATTEMPTS)
    run = run_scenario("full_stack_on_mock", sid=SID, question=QUESTION, n=1.85)
    yield run, tmp_path, before
    clear_session(SID)


def _plots(text):
    return [json.loads(m.group(0).split("__PRC_PLOT__", 1)[1].strip())
            for m in app._PLOT_BLOCK_RE.finditer(text)]


def test_tool_dispatch_through_answer_assembly(stack):
    run, _, _ = stack
    tools = [c["tool"] for c in run.ledger]
    assert tools == ["fit_petrophysical_curve", "sandbox_fit_archie", "generate_executive_report"]
    assert [c["status"] for c in run.ledger] == ["success"] * 3
    assert run.calls("fit_petrophysical_curve")[0]["values"]["n"] == pytest.approx(1.85, abs=1e-3)
    assert run.calls("sandbox_fit_archie")[0]["values"] == {}       # a clamped fit records no number
    # Four model calls: three tool turns and the final text turn.
    assert [t["step"] for t in run.transcript] == [0, 1, 2, 3]
    assert "Executive SCAL Report" in run.reply                     # the report tool's render reached the answer


def test_gate_value_binding_and_word_bounded_parameter(stack):
    run, _, _ = stack
    assert "1.999" not in run.reply
    assert "[unverified - value differs from the fitted result]" in run.reply
    # The correct value survives in prose and in the mandated table cell.
    assert "n = 1.850" in run.reply
    assert re.search(r"\| Archie Saturation Exponent n \| 1\.850 \|", run.reply)
    # The `a` inside "saturation" was never read as parameter `a`: the word is intact
    # everywhere and the strip happened on `n`.
    assert run.reply.count("saturation exponent") == 2
    assert re.search(r"fitted saturation exponent n = \[unverified - value differs", run.reply)


def test_plot_provenance_fitted_and_unfitted_payloads(stack):
    run, _, _ = stack
    plots = _plots(run.reply)
    assert len(plots) == 2
    fit, sandbox = plots
    assert fit["metadata"]["archie"]["n"] == pytest.approx(1.85, abs=1e-3)
    assert any(re.search(r"RI Archie\s+n=1\.85", c["name"]) for c in fit["curves"])
    assert sandbox["metadata"]["archie"]["fitted"] is False and sandbox["metadata"]["archie"]["n"] is None
    assert any("not fitted" in c["name"] for c in sandbox["curves"])
    assert not any(re.search(r"\bn=\d", c["name"]) for c in sandbox["curves"])
    assert "1.500" not in run.reply                                # the clamp bound never surfaces as a value


def test_a3_provenance_notice_reaches_the_generated_docx(stack):
    run, vault, _ = stack
    files = list(vault.glob("*.docx"))
    assert len(files) == 1, files
    text = "\n".join(p.text for p in Document(str(files[0])).paragraphs)
    assert "Parameter Provenance" in text
    assert "substituted" in text.lower() and "Swi" in text


def test_tokens_resolve_at_assembly(stack):
    run, _, _ = stack
    assert "{{" not in run.reply
    assert f"{WETTABILITY['Wettability.Amott_Water_Index_Iw']:.3f}" in run.reply


def test_clamped_sandbox_fit_never_enters_the_session_cache(stack):
    """A corrected (clamped) sandbox fit is not a fitted value: it must not be
    bound into labeled_values, or a `{{val:n}}` token would render the clamp
    bound as `1.500 · CACHED · HIGH`. The cache-path fit's 1.85 stays."""
    run, _, _ = stack
    with app.SESSION_DATA_CACHE_LOCK:
        labeled = dict(app.SESSION_DATA_CACHE[SID]["labeled_values"])
    assert labeled["n"] == pytest.approx(1.85, abs=1e-3)
    assert "b" not in labeled                                       # nothing from the clamped fit
    assert "n = 1.850 · CACHED · HIGH" in run.reply
    assert "1.500" not in run.reply


def test_zero_egress_and_still_the_keyless_mock(stack):
    _, _, before = stack
    assert len(egress_guard.ATTEMPTS) == before
    assert app.CHAT.config.provider == "mock" and app.CHAT.config.api_keys == ()
    assert app.CHAT.script is None                                  # the scenario was unloaded after the run
