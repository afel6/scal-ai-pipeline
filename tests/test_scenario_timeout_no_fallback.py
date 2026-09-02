"""D2.1 / D2.3 — a scripted provider timeout and a slow response, through the
real chat loop and the real /api/chat route, with no server and no clock.

C1's no-fallback path: when the model times out, scal produces NO answer —
chat() raises, the route answers status "error" with a processing-error reply
and zero fitted-parameter shapes; no other provider is tried (the adapter is
still the keyless mock) and nothing is invented. A slow-but-complete response
is delivered intact. Every wait (retry back-off and the scripted delay) is
recorded through injected sleepers, never actually slept.
"""
import re
import time

import pytest
from fastapi.testclient import TestClient

import app
import llm_adapter as la
from scenario_support import EMAIL, clear_session, load_scenario, run_scenario, seed_session

SID = "d2-timeout"
QUESTION = "Report the Archie saturation exponent n for sample D2-1."


@pytest.fixture(autouse=True)
def waits(monkeypatch):
    recorded = []
    monkeypatch.setattr(time, "sleep", lambda s: recorded.append(("retry", float(s))))
    monkeypatch.setattr(app.CHAT, "sleeper", lambda s: recorded.append(("mock", float(s))))
    clear_session(SID)
    yield recorded
    clear_session(SID)


def test_timeout_raises_out_of_chat_with_no_answer_and_no_fallback(waits):
    with pytest.raises(la.ChatAdapterError, match="(?i)timed out"):
        run_scenario("timeout_no_fallback", sid=SID, question=QUESTION)
    # Five attempts, each hitting the scripted 300 s timeout — recorded, not slept.
    assert [w for w in waits if w[0] == "mock"] == [("mock", 300.0)] * 5
    assert [w for w in waits if w[0] == "retry"] == [("retry", 2.0), ("retry", 4.0), ("retry", 8.0), ("retry", 16.0)]
    # No provider switch, no key, no tool ran, nothing written as an answer.
    assert app.CHAT.config.provider == "mock" and app.CHAT.config.api_keys == ()
    assert app.get_tool_call_records(SID) == []


def test_route_reports_the_timeout_as_an_error_with_no_fabricated_content(waits):
    seed_session(SID)
    script = load_scenario("timeout_no_fallback")
    app.CHAT.load_script(script)
    try:
        r = TestClient(app.app).post("/api/chat", data={"message": QUESTION, "session_id": SID,
                                                        "user_email": EMAIL})
    finally:
        app.CHAT.load_script(None)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "error"
    assert "timed out" in body["reply"].lower()
    assert not re.search(r"\b(n|nw|no|m|a)\s*(?:=|is)\s*\d", body["reply"])
    assert "__PRC_PLOT__" not in body["reply"]
    # The retry budget this scenario exposes: the route retries a transient error
    # 5x on top of chat_generate_with_retry's 5 → 25 provider attempts per request
    # (at a 300 s timeout that is ~2 h before the user hears anything). Pinned so a
    # change in either loop is a deliberate one.
    assert len(script.transcript) == 25
    assert [w for w in waits if w[0] == "mock"] == [("mock", 300.0)] * 25


def test_slow_response_is_delivered_intact(waits):
    run = run_scenario("slow_response", sid=SID, question=QUESTION)
    assert ("mock", 45.0) in waits
    assert "Slow but complete" in run.reply
    assert "0.680" in run.reply and "{{" not in run.reply       # assembly still ran
    assert run.ledger == []
