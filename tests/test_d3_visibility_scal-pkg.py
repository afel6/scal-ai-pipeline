"""D3.1 visibility — batch scal-pkg (hviel/utils/units.py, hviel/rakeza/
dispatcher.py + contracts.py, llm_adapter.py).

Every test forces the failure (a fake transport / a monkeypatched worker call
/ a bad unit) and asserts what the CALLER sees: a raised exception, a field on
the returned envelope, or which liveness hook fired. A log line alone never
passes. No socket is opened: the adapter gets a fake opener, the dispatcher a
monkeypatched _post_json.
"""
import io
import json

import pytest

import llm_adapter as la
from hviel.rakeza import contracts, dispatcher
from hviel.utils import units


# ── units.py ────────────────────────────────────────────────────────────────

def test_convert_unknown_unit_raises_instead_of_passing_through():
    with pytest.raises(ValueError, match="psig"):
        units.convert_pressure(100.0, "psig")
    with pytest.raises(ValueError, match="R"):
        units.convert_temperature(500.0, "R")
    with pytest.raises(ValueError, match="m2"):
        units.convert_permeability(1e-12, "m2")
    with pytest.raises(ValueError, match="poise"):
        units.convert_viscosity(1.0, "poise")
    # Fahrenheit is the target unit: an explicit identity, not a fall-through.
    assert units.convert_temperature(200.0, "F") == 200.0
    assert units.convert_temperature(200.0, "fahrenheit") == 200.0
    with pytest.raises(ValueError):
        units.normalize_value(1.0, "pressure", "kg/cm2")


def test_detect_unit_only_reports_units_it_can_convert():
    # Known units still detect.
    assert units.detect_unit("Pressure (bar)") == ("pressure", "bar")
    assert units.detect_unit("T [C]") == ("temperature", "C")
    assert units.detect_unit("Temp (F)") == ("temperature", "F")
    # Unknown units and false positives of the single-letter p/t/k pattern
    # must NOT be reported (the caller labels every hit "[UNITS NORMALIZED]").
    assert units.detect_unit("Pressure (psig)") is None
    assert units.detect_unit("P (kg/cm2)") is None
    assert units.detect_unit("t (min)") is None
    assert units.detect_unit("k (fraction)") is None
    assert units.detect_unit("K (m2)") is None
    assert units.detect_unit("Viscosity (cSt)") is None


# ── dispatcher.py / contracts.py ────────────────────────────────────────────

def _req(agent):
    return contracts.DelegationRequest(
        task_id="t1", agent=agent, domain=contracts.AGENT_DOMAIN[agent], query="q")


def test_hviel_status_error_reply_is_a_failed_envelope(monkeypatch):
    monkeypatch.setattr(dispatcher, "_post_json", lambda *a, **k: {
        "status": "error", "session_id": "s",
        "reply": "Processing error: boom. Please retry or contact PRC support."})
    resp = dispatcher.dispatch(_req(contracts.WorkerAgent.HVIEL))
    assert resp.ok is False
    assert "Processing error: boom" in (resp.error or "")
    assert resp.answer == ""


def test_aviel_status_error_reply_is_a_failed_envelope(monkeypatch):
    monkeypatch.setattr(dispatcher, "_post_json", lambda *a, **k: {
        "status": "error", "text": "chat provider unavailable"})
    resp = dispatcher.dispatch(_req(contracts.WorkerAgent.AVIEL))
    assert resp.ok is False
    assert "chat provider unavailable" in (resp.error or "")


def test_worker_degradations_ride_on_the_envelope_and_reach_synthesis(monkeypatch):
    monkeypatch.setattr(dispatcher, "_post_json", lambda *a, **k: {
        "status": "success", "reply": "Swi is 0.22",
        "degradations": ["kb_search: chroma unavailable"]})
    resp = dispatcher.dispatch(_req(contracts.WorkerAgent.HVIEL))
    assert resp.ok is True and resp.answer == "Swi is 0.22"
    assert resp.degradations == ["kb_search: chroma unavailable"]
    prompt = contracts.build_synthesis_prompt("q", [resp])
    assert "kb_search: chroma unavailable" in prompt
    assert "DEGRADED" in prompt


def test_aviel_fallback_marker_rides_on_the_envelope(monkeypatch):
    monkeypatch.setattr(dispatcher, "_post_json", lambda *a, **k: {
        "text": "PVT evaluation ...", "payload": {},
        "degradations": ["chat_provider: ChatAdapterError: all keys failed"]})
    resp = dispatcher.dispatch(_req(contracts.WorkerAgent.AVIEL))
    assert resp.ok is True
    assert resp.degradations == ["chat_provider: ChatAdapterError: all keys failed"]
    assert "chat_provider" in contracts.build_synthesis_prompt("q", [resp])


# ── llm_adapter.py ──────────────────────────────────────────────────────────

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _BrokenStream:
    """Yields one SSE chunk, then the connection dies mid-stream."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        raise ConnectionResetError("peer reset")


def _adapter(bodies, hooks):
    """bodies: list of bytes | response objects returned in order by the fake opener."""
    def opener(url, headers, body, timeout):
        out = bodies.pop(0)
        return out if hasattr(out, "__enter__") else _Resp(out)

    cfg = la.ChatConfig(provider="nvidia", model="m",
                        base_url="https://example.invalid/v1/chat/completions",
                        api_keys=("k-alpha",), timeout=5.0)
    return la.ChatAdapter(cfg, opener=opener,
                          on_success=lambda: hooks.append("ok"),
                          on_failure=lambda m: hooks.append(("fail", m)))


def _body(choices, usage=None):
    return json.dumps({"choices": choices, "usage": usage or {}}).encode()


MSG = [{"role": "user", "content": "q"}]


def test_malformed_http_timeout_is_a_config_error():
    with pytest.raises(la.ChatAdapterError, match="LLM_HTTP_TIMEOUT"):
        la.load_config({"LLM_PROVIDER": "ollama", "LLM_HTTP_TIMEOUT": "soon"})
    with pytest.raises(la.ChatAdapterError, match="NVIDIA_HTTP_TIMEOUT"):
        la.load_config({"LLM_PROVIDER": "nvidia", "NVIDIA_HTTP_TIMEOUT": "5s"})
    assert la.load_config({"LLM_PROVIDER": "ollama", "LLM_HTTP_TIMEOUT": "12"}).timeout == 12.0


def test_complete_no_choices_raises_with_provider_body_and_records_failure():
    hooks = []
    ad = _adapter([json.dumps({"error": {"message": "quota exceeded"}}).encode()], hooks)
    with pytest.raises(la.ChatAdapterError, match="quota exceeded"):
        ad.complete(MSG)
    assert hooks and hooks[0][0] == "fail" and "quota exceeded" in hooks[0][1]
    assert "ok" not in hooks


def test_complete_non_json_body_records_failure_then_raises():
    hooks = []
    ad = _adapter([b"<html>502 Bad Gateway</html>"], hooks)
    with pytest.raises(la.ChatAdapterError, match="not JSON"):
        ad.complete(MSG)
    assert hooks == [("fail", hooks[0][1])] and "502" in hooks[0][1]


def test_complete_garbled_tool_call_arguments_raise_instead_of_empty_args():
    for bad in ("{not json", "[1, 2]"):
        hooks = []
        ad = _adapter([_body([{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c0", "type": "function", "function": {"name": "fit", "arguments": bad}}]}}])], hooks)
        with pytest.raises(la.ChatAdapterError, match="fit"):
            ad.complete(MSG, tools=[{"type": "function", "function": {"name": "fit"}}])


def test_complete_exposes_finish_reason_and_refuses_a_blocked_reply():
    hooks = []
    ad = _adapter([_body([{"message": {"role": "assistant", "content": "partial"},
                           "finish_reason": "length"}])], hooks)
    res = ad.complete(MSG)
    assert res.text == "partial" and res.finish_reason == "length"
    assert hooks == ["ok"]

    hooks = []
    ad = _adapter([_body([{"message": {"role": "assistant", "content": ""},
                           "finish_reason": "content_filter"}])], hooks)
    with pytest.raises(la.ChatAdapterError, match="content_filter"):
        ad.complete(MSG)


def test_complete_success_hook_only_after_a_real_message():
    hooks = []
    ad = _adapter([_body([{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}])], hooks)
    assert ad.complete(MSG).text == "hi"
    assert hooks == ["ok"]


def test_stream_error_event_raises_and_records_failure():
    hooks = []
    sse = b"".join([
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
        b'data: {"error":{"message":"rate limited","code":429}}\n\n',
        b"data: [DONE]\n\n",
    ])
    ad = _adapter([sse], hooks)
    gen = ad.stream(MSG)
    assert next(gen) == "Hel"
    with pytest.raises(la.ChatAdapterError, match="rate limited"):
        next(gen)
    assert hooks and hooks[0][0] == "fail"
    assert "ok" not in hooks


def test_stream_malformed_chunk_raises_instead_of_shortening_the_reply():
    hooks = []
    sse = b'data: {"choices":[{"delta":{"content":"A"}}]}\n\ndata: {broken\n\ndata: [DONE]\n\n'
    ad = _adapter([sse], hooks)
    with pytest.raises(la.ChatAdapterError, match="malformed"):
        list(ad.stream(MSG))
    assert "ok" not in hooks


def test_stream_without_any_message_is_a_failure_not_a_success():
    hooks = []
    ad = _adapter([b"data: [DONE]\n\n"], hooks)
    with pytest.raises(la.ChatAdapterError):
        list(ad.stream(MSG))
    assert hooks and hooks[0][0] == "fail"
    assert "ok" not in hooks


def test_stream_mid_stream_connection_error_records_failure():
    hooks = []
    ad = _adapter([_BrokenStream()], hooks)
    gen = ad.stream(MSG)
    assert next(gen) == "Hel"
    with pytest.raises(ConnectionResetError):
        next(gen)
    assert hooks and hooks[0][0] == "fail" and "peer reset" in hooks[0][1]
    assert "ok" not in hooks


def test_stream_success_hook_fires_once_after_a_delivered_message():
    hooks = []
    sse = b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n'
    ad = _adapter([sse], hooks)
    assert list(ad.stream(MSG)) == ["Hi"]
    assert hooks == ["ok"]
