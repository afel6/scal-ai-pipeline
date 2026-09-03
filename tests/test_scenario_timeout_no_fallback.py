"""D2.1 / D2.3 / D3.3 — a scripted provider timeout and a slow response, through
the real chat loop and the real /api/chat route, with no server and no clock.

C1's no-fallback path: when the model times out, scal produces NO answer —
chat() ends the request with a plain statement, the route answers status
"error" with that statement and zero fitted-parameter shapes; no other
provider is tried (the adapter is still the keyless mock) and nothing is
invented. A slow-but-complete response is delivered intact. Every wait (the
one-second back-off between attempts and the scripted delay) is recorded
through injected sleepers, never actually slept.

Budget (D3.3): LLM_MAX_ATTEMPTS=2 provider calls per request, no route-level
retries on top — the old 5 × 5 = 25 attempts (~2 h at a 300 s timeout) is
gone; the wall clock (LLM_MAX_WALL_SECONDS=300) is the outer guarantee.
"""
import re
import time

import pytest
from fastapi.testclient import TestClient

import app
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


def test_timeout_ends_the_request_plainly_with_no_fallback(waits):
    run = run_scenario("timeout_no_fallback", sid=SID, question=QUESTION)
    # Two attempts, each hitting the scripted 300 s timeout — recorded, not slept —
    # with one short back-off between them. Nothing else was tried.
    assert [w for w in waits if w[0] == "mock"] == [("mock", 300.0)] * 2
    assert [w for w in waits if w[0] == "retry"] == [("retry", 1.0)]
    assert "did not answer" in run.reply.lower() and "2 attempt" in run.reply
    assert app.CHAT.config.provider == "mock" and app.CHAT.config.api_keys == ()
    assert app.get_tool_call_records(SID) == []
    assert not re.search(r"\b(n|nw|no|m|a)\s*(?:=|is)\s*\d", run.reply)


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
    assert "did not answer" in body["reply"].lower() and "timed out" in body["reply"].lower()
    assert not re.search(r"\b(n|nw|no|m|a)\s*(?:=|is)\s*\d", body["reply"])
    assert "__PRC_PLOT__" not in body["reply"]
    # The budget is the whole story: the route adds no attempts of its own.
    assert len(script.transcript) == 2
    assert [w for w in waits if w[0] == "mock"] == [("mock", 300.0)] * 2


def test_slow_response_is_delivered_intact(waits):
    run = run_scenario("slow_response", sid=SID, question=QUESTION)
    assert ("mock", 45.0) in waits
    assert "Slow but complete" in run.reply
    assert "0.680" in run.reply and "{{" not in run.reply       # assembly still ran
    assert run.ledger == []
