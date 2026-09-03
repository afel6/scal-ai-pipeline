"""D3.1 — the three known "failure nobody could see" defects, named, with the
visibility each caller now gets. One disease, three sites, three files:

 (a) app.py tool loop / formatter: the analytic fits ran inside the FORMATTER,
     so a "⚠" refusal never flipped tool_ok and the loop told the model
     "plot computed, state Archie n".
 (b) app.py sandbox dispatch: a CLAMPED fit (corrected=True) was bound into
     labeled_values and could render "1.500 · CACHED · HIGH".
 (c) hviel/rag/router.py: a lazy `from src.rakeza.contracts import …` failed
     under package shadowing and surfaced only as a log line ("routing failed").

Each test forces the failure and asserts the CALLER sees it — the model (tool
result), the user (answer text), the route's client (JSON) — not a log line.
"""
import json

import pytest
from fastapi.testclient import TestClient

import app
import tools_registry as tr
from scenario_support import EMAIL, clear_session, run_scenario, seed_session

SID = "d3-known"


@pytest.fixture(autouse=True)
def _clean():
    clear_session(SID)
    yield
    clear_session(SID)


# (a) refusal inside the formatter → the model is told a failure, never "computed"
def test_a_formatter_refusal_is_a_failed_step_for_the_model():
    run = run_scenario("fabricated_value_after_failed_fit", sid=SID,
                       question="Report the Archie saturation exponent n for sample D3-1.", n=1.2)
    row = run.calls("fit_petrophysical_curve")[-1]
    assert row["status"] == "error" and row["values"] == {}
    content = run.tool_messages(1)[0]["content"]
    assert '"status": "error"' in content and "TOOL FAILURE" in content and "computed" not in content
    # And the contract says the same thing from the outcome alone.
    res = tr.normalize(tr.REGISTRY["fit_petrophysical_curve"], '{"status": "ready", "model": "ri"}',
                       "⚠️ Physics boundary check failed …", dispatch_ok=True)
    assert res.ok is False


# (b) a clamped fit never becomes a CACHED value
def test_b_clamped_sandbox_fit_is_never_bound_as_a_cached_value(monkeypatch):
    import physics_sandbox
    monkeypatch.setattr(physics_sandbox, "run_sandboxed",
                        lambda source, inputs=None: {"parameters": {"n": 1.5, "b": 1.0}, "corrected": True,
                                                     "coordinates": {}, "health": {}})
    seed_session(SID, n=1.85)
    app._tls.current_session_id = SID
    list(app.assistant._execute_tool(app._ChatFuncCall("sandbox_fit_archie",
                                                        {"x": [0.9, 0.5], "y": [1.1, 3.0], "model_type": "RI"})))
    with app.SESSION_DATA_CACHE_LOCK:
        labeled = dict(app.SESSION_DATA_CACHE[SID]["labeled_values"])
    assert "n" not in labeled and "b" not in labeled
    rendered = app.process_provenance_tokens("n = {{val:n}}", SID)
    assert "1.500" not in rendered and "CACHED" not in rendered


# (c) a RAG-router failure reaches the caller, not only the log
def test_c_router_failure_is_visible_to_every_caller(monkeypatch):
    import hviel.rag.router as router

    def boom(*a, **k):
        raise ImportError("No module named 'src.rakeza' (simulated shadowing)")
    monkeypatch.setattr(router, "classify_query", boom)
    run = run_scenario("slow_response", sid=SID, question="What does the Amott index measure?")
    # the user sees it in the answer …
    assert "[degraded: rag-router: ImportError" in run.reply
    # … and the route's client sees it in the JSON.
    monkeypatch.setattr(app.CHAT, "sleeper", lambda s: None)
    seed_session(SID)
    app.CHAT.load_script(app.llm_adapter.MockScript.from_file(
        __import__("scenario_support").FIXTURES / "slow_response.json"))
    try:
        r = TestClient(app.app).post("/api/chat", data={"message": "What does the Amott index measure?",
                                                        "session_id": SID, "user_email": EMAIL})
    finally:
        app.CHAT.load_script(None)
    body = r.json()
    assert body["status"] == "success"
    assert any(d.startswith("rag-router: ImportError") for d in body["degradations"]), body


def test_no_degradation_means_no_trailer_and_an_empty_list():
    run = run_scenario("slow_response", sid=SID, question="What does the Amott index measure?")
    assert "[degraded:" not in run.reply and app.degradations() == []


# The contract in the loop: an unknown tool or a malformed call is a failed step the model sees.
def test_unknown_tool_and_malformed_call_are_failed_steps():
    app._tls.current_session_id = SID
    final = list(app.assistant._execute_tool(app._ChatFuncCall("no_such_tool", {})))[-1]
    assert final[1] is False and "unknown tool" in json.loads(final[2])["error"].lower()
    final = list(app.assistant._execute_tool(app._ChatFuncCall("sandbox_fit_archie", {"x": [1], "bogus": 2})))[-1]
    err = json.loads(final[2])["error"]
    assert final[1] is False and "missing required argument: y" in err and "unknown argument: bogus" in err
