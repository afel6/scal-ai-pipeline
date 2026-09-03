"""D3.3 — one retry budget per chat request: bounded attempts AND bounded wall
clock, the wall clock being the outer guarantee.

Before: chat_generate_with_retry made 5 attempts, _generate retried the turn
3×, and /api/chat retried "transient" errors 5× on top — up to 25 provider
attempts, ~2 h at a 300 s timeout, on a single local model server that every
other agent (the supervisor mid-delegation included) queues behind. Now a
request gets one RetryBudget: at most LLM_MAX_ATTEMPTS provider calls and at
most LLM_MAX_WALL_SECONDS of wall time; the next attempt's HTTP timeout is
capped to what is left; exhaustion ends the request with a plain statement
and nothing invented.
"""
import re
import time

import pytest
from fastapi.testclient import TestClient

import app
import llm_adapter as la
import retry_budget as rb
from scenario_support import EMAIL, clear_session, load_scenario, run_scenario, seed_session

SID = "d3-budget"
QUESTION = "Report the Archie saturation exponent n for sample D3-1."


# --- the budget object ------------------------------------------------------------

def test_defaults_are_sized_for_one_local_model_server():
    b = rb.RetryBudget()
    assert b.max_attempts == 2
    assert b.max_wall_seconds == 300.0


def test_env_sizes_the_budget(monkeypatch):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("LLM_MAX_WALL_SECONDS", "45")
    b = rb.RetryBudget.from_env()
    assert (b.max_attempts, b.max_wall_seconds) == (4, 45.0)


def test_failed_attempts_are_bounded_but_successful_turns_are_free():
    b = rb.RetryBudget(max_attempts=2, max_wall_seconds=1000, clock=lambda: 0.0)
    for _ in range(5):                    # a multi-turn conversation: successes never spend the budget
        b.begin_attempt()
    b.record_failure("timed out"); b.begin_attempt()
    b.record_failure("timed out")
    with pytest.raises(rb.BudgetExhausted, match="2 attempt"):
        b.begin_attempt()


def test_wall_clock_is_the_outer_guarantee():
    now = {"t": 0.0}
    b = rb.RetryBudget(max_attempts=10, max_wall_seconds=300, clock=lambda: now["t"])
    b.begin_attempt()
    now["t"] = 280.0                      # 20 s left: an attempt may start, capped to what is left
    b.begin_attempt()
    assert b.attempt_timeout(default=300.0) == pytest.approx(20.0)
    now["t"] = 301.0
    with pytest.raises(rb.BudgetExhausted, match="300"):
        b.begin_attempt()


def test_attempt_timeout_never_exceeds_the_provider_default():
    b = rb.RetryBudget(max_attempts=3, max_wall_seconds=1000, clock=lambda: 0.0)
    b.begin_attempt()
    assert b.attempt_timeout(default=120.0) == 120.0


def test_exhaustion_message_states_the_facts_and_invents_nothing():
    now = {"t": 0.0}
    b = rb.RetryBudget(max_attempts=2, max_wall_seconds=300, clock=lambda: now["t"])
    b.begin_attempt(); b.record_failure("timed out"); now["t"] = 150.0
    b.begin_attempt(); b.record_failure("timed out"); now["t"] = 305.0
    msg = b.exhausted_message("timed out")
    assert "2 attempt" in msg and "305" in msg and "nothing" in msg.lower()
    assert not re.search(r"\b(n|nw|no|m|a)\s*=\s*\d", msg)


# --- through the real chat loop on mock --------------------------------------------

@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    waits = []
    monkeypatch.setattr(time, "sleep", lambda s: waits.append(("retry", float(s))))
    monkeypatch.setattr(app.CHAT, "sleeper", lambda s: waits.append(("mock", float(s))))
    clear_session(SID)
    yield waits
    clear_session(SID)


def test_chat_stops_at_the_attempt_bound_and_answers_plainly(_fast):
    run = run_scenario("timeout_no_fallback", sid=SID, question=QUESTION)
    assert len(run.transcript) == 2                        # LLM_MAX_ATTEMPTS, not 5, not 25
    assert "did not answer" in run.reply.lower() and "2 attempt" in run.reply
    assert "[mock:" not in run.reply and "__PRC_PLOT__" not in run.reply
    assert not re.search(r"\b(n|nw|no|m|a)\s*(?:=|is)\s*\d", run.reply)
    assert app.get_tool_call_records(SID) == []


def test_route_does_not_retry_on_top_of_the_budget(_fast):
    seed_session(SID)
    script = load_scenario("timeout_no_fallback")
    app.CHAT.load_script(script)
    try:
        r = TestClient(app.app).post("/api/chat", data={"message": QUESTION, "session_id": SID, "user_email": EMAIL})
    finally:
        app.CHAT.load_script(None)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert len(script.transcript) == 2                     # the route added no attempts of its own
    assert "did not answer" in body["reply"].lower()


def test_wall_clock_bound_terminates_a_slow_provider(monkeypatch, _fast):
    """Each attempt takes 200 s of wall time (fake clock): the second attempt
    would start past the 300 s bound — the request ends with a plain report."""
    now = {"t": 1000.0}

    def sleeper(s):                                      # the scripted delay advances the fake clock
        now["t"] += s
        _fast.append(("mock", s))
    monkeypatch.setattr(app.CHAT, "sleeper", sleeper)
    monkeypatch.setattr(rb, "_now", lambda: now["t"])
    script = la.MockScript.from_dict({"name": "slow-timeouts", "steps": [{"timeout": {"after": 200.0}}] * 5})
    app.CHAT.load_script(script)
    try:
        seed_session(SID)
        reply = app.assistant.chat([], QUESTION, stream=False, sid=SID, email=EMAIL)
    finally:
        app.CHAT.load_script(None)
    assert len(script.transcript) == 2 and reply.lower().count("did not answer") == 1
    assert "300" in reply                                 # the wall bound is named


# --- the budget is the request's, never a stray caller's inheritance -----------------

def test_chat_releases_its_budget_when_it_raises(monkeypatch, _fast):
    """A request that dies with an exception must not leave its (possibly
    spent) budget on the context: the next provider call outside chat() - a
    title summary, a health probe, an in-process script - would be refused
    before any attempt and /health would never see the failures."""
    def boom(text, sid):
        raise RuntimeError("assembly crashed")
    monkeypatch.setattr(app, "enforce_citation_gate", boom)
    with pytest.raises(RuntimeError, match="assembly crashed"):
        run_scenario("slow_response", sid=SID, question="What does the Amott index measure?")
    assert getattr(app._tls, "retry_budget", None) is None


def test_a_stray_call_gets_its_own_fresh_budget(monkeypatch, _fast):
    """No budget on the context: a provider call outside chat() is bounded by
    a budget of its own, and every failed attempt reaches alerting."""
    import alerting
    app._tls.retry_budget = None
    alerting.record_llm_success()
    monkeypatch.setattr(app.CHAT, "_open", lambda url, headers, body, timeout: (_ for _ in ()).throw(ConnectionError("down")))
    monkeypatch.setattr(app.CHAT, "config", la.ChatConfig(provider="gemini", model="m", base_url="u",
                                                          api_keys=("k",), timeout=1.0))
    with pytest.raises(Exception, match="2 attempt"):
        app.chat_text_generate("ping")
    assert alerting.llm_health()["consecutive_failures"] == 2
    assert getattr(app._tls, "retry_budget", None) is None      # nothing left behind either


def test_chat_releases_its_budget_when_the_answer_is_assembled(_fast):
    run_scenario("slow_response", sid=SID, question="What does the Amott index measure?")
    assert getattr(app._tls, "retry_budget", None) is None
    seed_session(SID)
    app.CHAT.load_script(load_scenario("slow_response"))
    try:
        chunks = list(app.assistant.chat([], "What does the Amott index measure?", stream=True, sid=SID, email=EMAIL))
    finally:
        app.CHAT.load_script(None)
    assert chunks and getattr(app._tls, "retry_budget", None) is None
