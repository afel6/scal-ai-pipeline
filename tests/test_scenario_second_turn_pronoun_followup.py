"""D2.2 scenario — second-turn pronoun follow-up (C2 item 1.2).

Defect: "Explain the wettability part." has no referent on its own. The old
hub bridge forwarded that bare question, so the model never saw turn one
(sample D2-1) and answered about nothing in particular. Two scal-side guards,
proved on mock: (1) chat() carries `history` into the model's messages as
prior user/assistant turns, so the referent is there; (2) the hub's forwarded
thread envelope ("CONVERSATION SO FAR … CURRENT QUESTION: …") reaches the
model verbatim, so the referent survives even when the hub, not scal, holds
the thread.
"""
import uuid

import pytest

import app
from scenario_support import EMAIL, clear_session, load_scenario, seed_session

NAME = "second_turn_pronoun_followup"
SID = "d2-second_turn_pronoun_followup"
Q1 = "Analyze sample D2-1 in Well-D2."
Q2 = "Explain the wettability part."
REFERENT = "D2-1"
_fname = lambda: f"SCAL_upload_{uuid.uuid4().hex[:8]}.xlsx"     # referent-free, unique cache key


@pytest.fixture(autouse=True)
def _clean():
    clear_session(SID)
    yield
    clear_session(SID)


def play_two_turns(question2, history_for_turn2):
    """Two chat() calls on one loaded script (re-loading resets the cursor).

    Mirrors scenario_support.run_scenario; `history_for_turn2(reply1)` builds
    what the caller hands chat() on the follow-up. The seeded file name carries
    no 'D2-1' so the referent can only come from the thread itself."""
    script = load_scenario(NAME)
    app.CHAT.load_script(script)
    try:
        seed_session(SID, fname=_fname())
        r1 = app.assistant.chat([], Q1, stream=False, sid=SID, email=EMAIL)
        seed_session(SID, fname=_fname())          # fresh cache key for the second call
        r2 = app.assistant.chat(history_for_turn2(r1), question2(r1), stream=False, sid=SID, email=EMAIL)
    finally:
        app.CHAT.load_script(None)
    return r1, r2, script


def _texts(messages, role):
    return [m.get("content") or "" for m in messages if m.get("role") == role]


def test_history_puts_the_turn_one_referent_in_front_of_the_model():
    r1, r2, script = play_two_turns(
        lambda r1: Q2,
        lambda r1: [{"role": "user", "text": Q1}, {"role": "model", "text": r1}])
    assert REFERENT in r1 and r1 == script.steps[0].text
    assert r2 == script.steps[1].text and REFERENT in r2          # the scripted answer about D2-1
    msgs = script.transcript[1]["messages"]
    users, assistants = _texts(msgs, "user"), _texts(msgs, "assistant")
    # Prior turns are in the messages, in order, before the follow-up question.
    assert users[0] == Q1 and assistants == [r1], [m.get("role") for m in msgs]
    assert Q2 in users[-1] and REFERENT not in users[-1]           # the follow-up itself is referent-less …
    roles = [m["role"] for m in msgs]
    assert roles.index("user") < roles.index("assistant") < len(roles) - 1
    # … so the referent the model sees comes from the carried thread.
    assert any(REFERENT in t for t in users[:-1] + assistants)


def test_hub_thread_envelope_reaches_the_model_verbatim():
    envelope = lambda r1: (
        "CONVERSATION SO FAR (context for resolving references — answer only the CURRENT QUESTION below):\n"
        f"User: {Q1}\nHviel: {r1}\n\nCURRENT QUESTION: {Q2}")
    r1, r2, script = play_two_turns(envelope, lambda r1: [])
    assert r2 == script.steps[1].text and REFERENT in r2
    final_user = _texts(script.transcript[1]["messages"], "user")[-1]
    assert envelope(r1) in final_user                              # intact: not rewritten, not truncated
    assert final_user.count("CURRENT QUESTION: " + Q2) == 1


def test_without_history_the_model_gets_a_bare_referent_less_question():
    """The defect, reproduced (the old bridge): the follow-up arrives with no
    thread at all — the model sees no prior turns and no 'D2-1' anywhere."""
    _, _, script = play_two_turns(lambda r1: Q2, lambda r1: [])
    msgs = script.transcript[1]["messages"]
    assert {m["role"] for m in msgs} <= {"system", "user"}
    assert len(_texts(msgs, "user")) == 1
    assert not any(REFERENT in (m.get("content") or "") for m in msgs), msgs


def test_if_chat_dropped_history_the_referent_would_vanish(monkeypatch):
    """Guard-off on the scal side: a chat() that ignored `history` sends the
    same bare question even when the caller did pass the thread."""
    orig = type(app.assistant)._build_contents
    monkeypatch.setattr(type(app.assistant), "_build_contents",
                        lambda self, history, enriched, f_parts: orig(self, [], enriched, f_parts))
    _, _, script = play_two_turns(
        lambda r1: Q2,
        lambda r1: [{"role": "user", "text": Q1}, {"role": "model", "text": r1}])
    msgs = script.transcript[1]["messages"]
    assert not _texts(msgs, "assistant")
    assert not any(REFERENT in (m.get("content") or "") for m in msgs), msgs
