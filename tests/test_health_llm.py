"""B4 — /health must be able to report the chat LLM being down.

The old check only inspected GEMINI_KEY_POOL, which config.py guarantees is
non-empty, so /health could never fail for an unreachable provider. Health now
reads the same success/failure signal the chat path already feeds through
alerting.record_llm_success()/record_llm_failure() at every provider call — so
a provider outage that the chat path has hit is visible on /health, without
health reimplementing any provider logic (that is what would break at C2).
"""
import pytest
from fastapi.testclient import TestClient

import alerting
import app as scal_app

client = TestClient(scal_app.app)


def _reset():
    alerting.record_llm_success()  # zeroes the consecutive-failure counter


def test_health_ok_when_llm_succeeding():
    _reset()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_degraded_when_provider_unreachable():
    # Simulate what a real chat turn against an unreachable provider does:
    # _call_gemini_with_retry calls record_llm_failure on every failed attempt.
    _reset()
    for _ in range(5):
        alerting.record_llm_failure("connection refused")
    resp = client.get("/health")
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["status"] == "degraded"
    assert body.get("llm") in ("degraded", "down")


def test_health_recovers_after_success():
    _reset()
    for _ in range(5):
        alerting.record_llm_failure("boom")
    assert client.get("/health").status_code == 503
    alerting.record_llm_success()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_degrades_through_the_adapter(monkeypatch):
    """C2 2.2 — /health must report degraded when the ADAPTER fails, without
    the endpoint knowing any provider logic: the adapter's failure hook feeds
    alerting, /health reads alerting. Provider is unreachable here (the
    transport raises), a text call retries and fails, health flips to 503."""
    _reset()

    def dead_opener(url, headers, body, timeout):
        raise ConnectionError("provider unreachable")
    monkeypatch.setattr(scal_app.CHAT, "_open", dead_opener)
    monkeypatch.setattr(scal_app.CHAT, "config",
                        scal_app.llm_adapter.ChatConfig(provider="gemini", model="m",
                                                        base_url="u", api_keys=("k",), timeout=1.0))
    with pytest.raises(Exception):
        scal_app.chat_text_generate("ping", max_retries=3, base_delay=0)
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["llm"] == "degraded"
