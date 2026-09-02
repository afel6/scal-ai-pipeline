"""C2 Part 2 — the single provider-neutral chat adapter.

Every chat-LLM call in both repos routes through `llm_adapter.ChatAdapter`.
Provider and model come from the environment, never from code; the model a
result reports is the model that was actually sent on the wire; keys rotate
with a cooldown and never appear in logs or errors; success/failure hooks feed
the provider-neutral /health signal (B4). HTTP is faked here via an injected
opener — no network.
"""
import io
import json

import pytest

import llm_adapter as la


# --- config from environment ------------------------------------------------

def test_config_reads_provider_model_url_keys_from_env():
    env = {"LLM_PROVIDER": "gemini", "LLM_MODEL": "gemini-2.5-flash-lite",
           "LLM_API_KEYS": "k1, k2"}
    cfg = la.load_config(env)
    assert cfg.provider == "gemini"
    assert cfg.model == "gemini-2.5-flash-lite"
    assert cfg.base_url == la.PROVIDERS["gemini"]["base_url"]
    assert cfg.api_keys == ("k1", "k2")


def test_config_provider_default_model_when_unset():
    cfg = la.load_config({"LLM_PROVIDER": "nvidia", "LLM_API_KEY": "nv-1"})
    assert cfg.model == la.PROVIDERS["nvidia"]["model"]
    assert cfg.api_keys == ("nv-1",)


def test_config_legacy_names_supply_url_model_keys_once_provider_is_explicit():
    env = {"LLM_PROVIDER": "gemini",
           "SCAL_LLM_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
           "SCAL_LLM_MODEL": "gemini-2.5-flash", "NVIDIA_API_KEY": "legacy-key",
           "NVIDIA_API_KEY2": "legacy-key-2"}
    cfg = la.load_config(env)
    assert cfg.provider == "gemini"
    assert cfg.model == "gemini-2.5-flash"
    assert cfg.base_url.startswith("https://generativelanguage.googleapis.com")
    assert cfg.api_keys == ("legacy-key", "legacy-key-2")


# --- D0: a real provider is an explicit, deliberate opt-in ---------------------

def test_default_provider_is_mock_when_nothing_is_set():
    cfg = la.load_config({})
    assert cfg.provider == "mock"
    assert cfg.api_keys == ()


def test_legacy_url_or_keys_alone_never_select_a_real_provider():
    env = {"SCAL_LLM_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
           "SCAL_LLM_MODEL": "gemini-2.5-flash", "NVIDIA_API_KEY": "legacy-key",
           "LLM_BASE_URL": "https://integrate.api.nvidia.com/v1/chat/completions",
           "LLM_API_KEYS": "k1"}
    assert la.load_config(env).provider == "mock"


def test_agent_prefix_defaults_to_mock_until_opted_in():
    cfg = la.load_config({}, prefix="AGENT_LLM",
                         default_base_url="http://localhost:11434/v1/chat/completions",
                         default_model="gemma3n:e2b")
    assert cfg.provider == "mock"
    opted = la.load_config({"AGENT_LLM_PROVIDER": "ollama"}, prefix="AGENT_LLM",
                           default_base_url="http://localhost:11434/v1/chat/completions",
                           default_model="gemma3n:e2b")
    assert (opted.provider, opted.model) == ("ollama", "gemma3n:e2b")
    assert opted.base_url == "http://localhost:11434/v1/chat/completions"


def test_is_cloud_classifies_providers():
    assert [la.is_cloud(p) for p in ("nvidia", "gemini", "openai")] == [True, True, True]
    assert [la.is_cloud(p) for p in ("ollama", "mock")] == [False, False]


def test_mock_adapter_completes_and_streams_without_any_transport():
    def opener(*a, **k):
        raise AssertionError("mock provider must never open a connection")
    ad = la.ChatAdapter(la.load_config({}), opener=opener)
    msgs = [{"role": "user", "content": "what is porosity?"}]
    r1 = ad.complete(msgs, tools=[{"type": "function", "function": {"name": "fit"}}])
    r2 = ad.complete(msgs)
    assert r1.text and r1.text == r2.text                  # deterministic
    assert r1.model == "mock" and r1.tool_calls == []
    assert r1.text != ad.complete([{"role": "user", "content": "other"}]).text
    assert list(ad.stream(msgs)) == [r1.text]
    assert ad.keys_degraded() is False
    assert ad.state()["provider"] == "mock"


def test_config_ollama_needs_no_key():
    cfg = la.load_config({"LLM_PROVIDER": "ollama"})
    assert cfg.api_keys  # a placeholder so the loop runs once
    assert "11434" in cfg.base_url


def test_config_rejects_unknown_provider():
    with pytest.raises(la.ChatAdapterError):
        la.load_config({"LLM_PROVIDER": "skynet"})


# --- fake transport -----------------------------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _HTTPError(Exception):
    def __init__(self, code, body=b"nope"):
        super().__init__(f"HTTP {code}")
        self.code = code
        self._body = body

    def read(self):
        return self._body


def _opener_factory(script):
    """script: list of callables(request_dict) -> bytes | raises. Consumed in order."""
    calls = []

    def opener(url, headers, body, timeout):
        req = {"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout}
        calls.append(req)
        step = script.pop(0)
        out = step(req)
        return _Resp(out)
    opener.calls = calls
    return opener


def _ok(text="hello", tool_calls=None, model="m"):
    msg = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = [{"id": f"c{i}", "type": "function",
                              "function": {"name": n, "arguments": json.dumps(a)}}
                             for i, (n, a) in enumerate(tool_calls)]
    return json.dumps({"model": model, "choices": [{"message": msg}],
                       "usage": {"prompt_tokens": 7, "completion_tokens": 3}}).encode()


def _cfg(keys=("k-alpha", "k-beta"), provider="nvidia"):
    return la.ChatConfig(provider=provider, model="test-model",
                         base_url="https://example.invalid/v1/chat/completions",
                         api_keys=tuple(keys), timeout=5.0)


# --- complete() ---------------------------------------------------------------

def test_complete_builds_openai_payload_and_parses_text_and_tools():
    opener = _opener_factory([lambda r: _ok("the answer", [("fit", {"model": "ri"})])])
    ad = la.ChatAdapter(_cfg(), opener=opener)
    res = ad.complete([{"role": "user", "content": "q"}],
                      tools=[{"type": "function", "function": {"name": "fit"}}],
                      temperature=0.3, max_tokens=99)
    sent = opener.calls[0]
    assert sent["body"]["model"] == "test-model"
    assert sent["body"]["messages"] == [{"role": "user", "content": "q"}]
    assert sent["body"]["temperature"] == 0.3 and sent["body"]["max_tokens"] == 99
    assert sent["body"]["tools"][0]["function"]["name"] == "fit"
    assert sent["headers"]["authorization"] == "Bearer k-alpha"
    assert res.text == "the answer"
    assert res.tool_calls == [la.ToolCall("fit", {"model": "ri"})]
    assert res.usage == (7, 3)
    assert res.model == "test-model"   # what was sent, not what a shim pretends


def test_success_hook_fires_once():
    hits = []
    ad = la.ChatAdapter(_cfg(), opener=_opener_factory([lambda r: _ok()]),
                        on_success=lambda: hits.append("ok"), on_failure=lambda e: hits.append("fail"))
    ad.complete([{"role": "user", "content": "q"}])
    assert hits == ["ok"]


def test_failed_key_is_cooled_down_and_next_key_used():
    def boom(r):
        raise _HTTPError(401)
    opener = _opener_factory([boom, lambda r: _ok("second")])
    ad = la.ChatAdapter(_cfg(), opener=opener)
    res = ad.complete([{"role": "user", "content": "q"}])
    assert res.text == "second"
    assert opener.calls[0]["headers"]["authorization"] == "Bearer k-alpha"
    assert opener.calls[1]["headers"]["authorization"] == "Bearer k-beta"
    assert ad.keys_in_cooldown() == 1
    assert ad.keys_degraded() is False


def test_all_keys_failing_raises_fires_failure_hook_and_never_leaks_keys():
    def boom(r):
        raise _HTTPError(503, b"upstream down")
    fails = []
    ad = la.ChatAdapter(_cfg(), opener=_opener_factory([boom, boom]),
                        on_failure=fails.append)
    with pytest.raises(la.ChatAdapterError) as ei:
        ad.complete([{"role": "user", "content": "q"}])
    assert "k-alpha" not in str(ei.value) and "k-beta" not in str(ei.value)
    assert len(fails) == 1 and "k-alpha" not in fails[0]
    assert ad.keys_degraded() is True


def test_state_reports_provider_model_and_pool():
    ad = la.ChatAdapter(_cfg(provider="gemini"), opener=_opener_factory([]))
    st = ad.state()
    assert st["provider"] == "gemini" and st["model"] == "test-model"
    assert st["keys"] == 2 and st["keys_in_cooldown"] == 0
    assert "k-alpha" not in json.dumps(st)


def test_nvidia_gets_reasoning_effort_but_others_do_not():
    o1 = _opener_factory([lambda r: _ok()]); la.ChatAdapter(_cfg(provider="nvidia"), opener=o1).complete([{"role": "user", "content": "q"}])
    o2 = _opener_factory([lambda r: _ok()]); la.ChatAdapter(_cfg(provider="gemini"), opener=o2).complete([{"role": "user", "content": "q"}])
    assert o1.calls[0]["body"].get("reasoning_effort") == "low"
    assert "reasoning_effort" not in o2.calls[0]["body"]


def test_response_format_json_is_forwarded():
    o = _opener_factory([lambda r: _ok('{"db": "pvt"}')])
    la.ChatAdapter(_cfg(), opener=o).complete([{"role": "user", "content": "q"}],
                                              response_format={"type": "json_object"})
    assert o.calls[0]["body"]["response_format"] == {"type": "json_object"}


# --- stream() -----------------------------------------------------------------

def test_stream_yields_text_deltas_from_sse():
    sse = b"".join([
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
        b"data: [DONE]\n\n",
    ])
    o = _opener_factory([lambda r: sse])
    out = list(la.ChatAdapter(_cfg(), opener=o).stream([{"role": "user", "content": "q"}]))
    assert out == ["Hel", "lo"]
    assert o.calls[0]["body"]["stream"] is True


def test_reasoning_content_is_never_surfaced():
    body = json.dumps({"choices": [{"message": {"role": "assistant", "content": "",
                                                "reasoning_content": "secret chain of thought"}}],
                       "usage": {}}).encode()
    res = la.ChatAdapter(_cfg(), opener=_opener_factory([lambda r: body])).complete(
        [{"role": "user", "content": "q"}])
    assert res.text == "" and "secret" not in json.dumps(res.raw.get("choices")[0]["message"]["content"])
