"""D2.2 scenario — unresolved `{{val:…}}` tokens (B0.1: 3 of 10 runs).

Defect: `process_provenance_tokens` ran only in the HTTP routes; `chat()`'s
answer assembly applied the citation gate but not token resolution, so every
in-process caller (B0.1's harness, any future embedder of chat()) received
raw tokens — even for values that WERE in the session cache. The guard now
runs at assembly, where every caller is covered (the C2 1.1 principle).
"""
import pytest

import app
from scenario_support import clear_session, run_scenario

SID = "d2-val-tokens"
QUESTION = "Report the Amott indices and the free Archie n for sample D2-1."


@pytest.fixture(autouse=True)
def _clean():
    clear_session(SID)
    yield
    clear_session(SID)


def test_tokens_resolve_from_cache_or_become_explicit_markers_at_assembly():
    run = run_scenario("unresolved_val_tokens", sid=SID, question=QUESTION)
    reply = run.reply
    assert "{{val:" not in reply and "{{" not in reply, reply
    # Cached keys resolve to their cached value (3-decimal render).
    assert "0.680" in reply and "0.050" in reply and "3.200" in reply
    # An absent key is an explicit marker in prose …
    assert "[unverified — absent from cache]" in reply
    # … and an empty cell in the mandated table format (never a raw token).
    table_rows = [ln for ln in reply.splitlines() if ln.startswith("| Free-fit n")]
    assert table_rows and table_rows[0].split("|")[2].strip() == "-", table_rows


def test_route_and_in_process_assembly_agree():
    """Applying the route-side resolver again to chat()'s output changes nothing."""
    run = run_scenario("unresolved_val_tokens", sid=SID, question=QUESTION)
    assert app.process_provenance_tokens(run.reply, SID) == run.reply


def test_no_session_never_reaches_the_model():
    """Fail closed one layer earlier: with no session there is no data, and
    chat() refuses before any model turn — the scripted model is never asked,
    so no token can be emitted at all."""
    script = app.llm_adapter.MockScript.from_file(
        __import__("scenario_support").FIXTURES / "unresolved_val_tokens.json")
    app.CHAT.load_script(script)
    try:
        reply = app.assistant.chat([], QUESTION, stream=False, sid=None, email="test@prc.local")
    finally:
        app.CHAT.load_script(None)
    assert "{{" not in reply
    assert "can't answer" in reply.lower() and "no scal file data" in reply.lower()
    assert script.transcript == []                    # zero model calls


def test_without_the_assembly_resolver_the_tokens_would_leak(monkeypatch):
    """The defect, reproduced: bypass the resolver and the raw tokens reach the
    caller — proof that this scenario is load-bearing, not decorative."""
    monkeypatch.setattr(app, "process_provenance_tokens", lambda text, sid: text)
    run = run_scenario("unresolved_val_tokens", sid=SID, question=QUESTION)
    assert "{{val:Wettability.Amott_Water_Index_Iw}}" in run.reply
