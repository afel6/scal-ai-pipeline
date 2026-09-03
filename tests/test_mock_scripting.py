"""D2.1 — the mock provider runs scripted scenarios, opt-in per test.

D0's mock is a null provider (deterministic text, no tool calls) and stays the
default. A `MockScript` — loaded from a JSON fixture under
tests/fixtures/scenarios/ — plays an ordered sequence of assistant turns, tool
calls, errors, timeouts and slow responses, records a transcript of what the
model was sent, and is fully deterministic: no randomness, no clock
dependence (delays go through an injectable sleeper).
"""
import pathlib

import pytest

import llm_adapter as la

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "scenarios"
MSGS = [{"role": "user", "content": "report the fitted n for B0-7"}]
FIT_TOOL = [{"type": "function", "function": {"name": "fit_petrophysical_curve"}}]


def _adapter(**hooks):
    def opener(*a, **k):
        raise AssertionError("mock provider must never open a connection")
    return la.ChatAdapter(la.load_config({}), opener=opener, **hooks)


def _script(steps, **kw):
    return la.MockScript.from_dict({"name": "inline", "steps": steps, **kw})


# --- default stays the null provider ------------------------------------------

def test_null_mode_is_still_the_default():
    ad = _adapter()
    assert ad.script is None
    assert ad.complete(MSGS).text.startswith("[mock:")
    assert ad.complete(MSGS).tool_calls == []


def test_load_script_none_restores_null_mode():
    ad = _adapter()
    ad.load_script(_script([{"assistant": "scripted"}]))
    assert ad.complete(MSGS).text == "scripted"
    ad.load_script(None)
    assert ad.complete(MSGS).text.startswith("[mock:")


# --- ordered turns, tool calls, transcript -------------------------------------

def test_script_plays_assistant_turns_and_tool_calls_in_order():
    ad = _adapter()
    ad.load_script(_script([
        {"assistant": {"text": "", "tool_calls": [{"name": "fit_petrophysical_curve",
                                                    "args": {"model": "ri", "sample_name": "B0-7"}}]}},
        {"assistant": {"text": "n is 1.850"}},
    ]))
    r1 = ad.complete(MSGS, tools=FIT_TOOL)
    assert r1.text == "" and r1.model == "mock"
    assert r1.tool_calls == [la.ToolCall("fit_petrophysical_curve", {"model": "ri", "sample_name": "B0-7"})]
    r2 = ad.complete(MSGS + [{"role": "tool", "tool_call_id": "c0", "content": "ok"}])
    assert r2.text == "n is 1.850" and r2.tool_calls == []


def test_script_records_a_transcript_of_what_the_model_was_sent():
    ad = _adapter()
    ad.load_script(_script([{"assistant": "a"}, {"assistant": "b"}]))
    ad.complete(MSGS, tools=FIT_TOOL)
    later = MSGS + [{"role": "tool", "tool_call_id": "c0", "content": "ERROR: fit failed"}]
    ad.complete(later)
    t = ad.script.transcript
    assert [e["step"] for e in t] == [0, 1]
    assert t[0]["messages"] == MSGS and t[0]["tools"] == ["fit_petrophysical_curve"]
    assert t[1]["messages"] == later and t[1]["tools"] == []


def test_stream_plays_the_next_assistant_text():
    ad = _adapter()
    ad.load_script(_script([{"assistant": "streamed answer"}]))
    assert list(ad.stream(MSGS)) == ["streamed answer"]


# --- failures: error, timeout, slow ------------------------------------------------

def test_scripted_error_raises_adapter_error_and_fires_failure_hook():
    fails = []
    ad = _adapter(on_failure=fails.append)
    ad.load_script(_script([{"error": "HTTP 503 upstream overloaded"}]))
    with pytest.raises(la.ChatAdapterError, match="503"):
        ad.complete(MSGS)
    assert len(fails) == 1 and "503" in fails[0]


def test_scripted_timeout_waits_then_fails_like_an_exhausted_pool():
    sleeps, fails = [], []
    ad = _adapter(on_failure=fails.append)
    ad.sleeper = sleeps.append                       # no real clock dependence
    ad.load_script(_script([{"timeout": {"after": 300.0}}]))
    with pytest.raises(la.ChatAdapterError, match="(?i)timed out"):
        ad.complete(MSGS)
    assert sleeps == [300.0] and len(fails) == 1


def test_scripted_slow_response_delays_then_answers():
    sleeps = []
    ad = _adapter()
    ad.sleeper = sleeps.append
    ad.load_script(_script([{"slow": {"delay": 42.0, "text": "late but complete"}}]))
    assert ad.complete(MSGS).text == "late but complete"
    assert sleeps == [42.0]


# --- exhaustion + determinism ----------------------------------------------------

def test_exhausted_script_fails_loudly_by_default():
    ad = _adapter()
    ad.load_script(_script([{"assistant": "only one"}]))
    ad.complete(MSGS)
    with pytest.raises(la.ChatAdapterError, match="(?i)exhausted"):
        ad.complete(MSGS)


def test_exhausted_script_can_opt_into_null_mode():
    ad = _adapter()
    ad.load_script(_script([{"assistant": "only one"}], on_exhausted="null"))
    ad.complete(MSGS)
    assert ad.complete(MSGS).text.startswith("[mock:")


def test_same_scenario_same_output_every_replay():
    path = FIXTURES / "fabricated_value_after_failed_fit.json"
    outs = []
    for _ in range(2):
        ad = _adapter()
        ad.load_script(la.MockScript.from_file(path))
        outs.append([(r.text, r.tool_calls) for r in (ad.complete(MSGS, tools=FIT_TOOL), ad.complete(MSGS))])
    assert outs[0] == outs[1]


def test_scenarios_are_repo_fixtures_not_inline_strings():
    script = la.MockScript.from_file(FIXTURES / "fabricated_value_after_failed_fit.json")
    assert script.name == "fabricated_value_after_failed_fit"
    assert script.description                      # every scenario says what defect it replays
    assert script.steps[0].tool_calls[0].name == "fit_petrophysical_curve"


def test_malformed_step_is_rejected_at_load_time():
    with pytest.raises(la.ChatAdapterError, match="(?i)step"):
        _script([{"assistant": "ok", "error": "both"}])
    with pytest.raises(la.ChatAdapterError, match="(?i)step"):
        _script([{"surprise": "x"}])
