"""D0 — "LLM last" is enforced, not remembered.

A cloud chat provider (nvidia | gemini | openai) or a real Gemini embedding key
configured while a private database is reachable is a startup hard-fail. Local
providers (mock, ollama) are fine with a private database; a cloud provider is
fine with no private database (the quarantined gate runs use a scratch store).
"""
import pytest

import app as scal_app
import llm_adapter as la


def _cfg(provider):
    keys = () if provider == "mock" else ("k",)
    return la.ChatConfig(provider=provider, model="m", base_url="u", api_keys=keys, timeout=1.0)


@pytest.fixture(autouse=True)
def _no_real_embedding_key(monkeypatch):
    monkeypatch.setattr(scal_app, "GEMINI_KEY_POOL", ["DUMMY_KEY"])


@pytest.mark.parametrize("provider", ["gemini", "nvidia", "openai"])
def test_cloud_provider_with_reachable_private_db_hard_fails(monkeypatch, provider):
    monkeypatch.setattr(scal_app.CHAT, "config", _cfg(provider))
    monkeypatch.setattr(scal_app, "_private_db_reachable", lambda: True)
    with pytest.raises(RuntimeError, match="(?i)cloud.*private database"):
        scal_app.assert_no_cloud_llm_with_private_db()


@pytest.mark.parametrize("provider", ["mock", "ollama"])
def test_local_providers_are_allowed_with_a_private_db(monkeypatch, provider):
    monkeypatch.setattr(scal_app.CHAT, "config", _cfg(provider))
    monkeypatch.setattr(scal_app, "_private_db_reachable", lambda: True)
    scal_app.assert_no_cloud_llm_with_private_db()          # must not raise


def test_cloud_provider_without_a_private_db_is_allowed(monkeypatch):
    monkeypatch.setattr(scal_app.CHAT, "config", _cfg("gemini"))
    monkeypatch.setattr(scal_app, "_private_db_reachable", lambda: False)
    scal_app.assert_no_cloud_llm_with_private_db()          # must not raise


def test_a_real_embedding_key_counts_as_a_cloud_provider(monkeypatch):
    monkeypatch.setattr(scal_app.CHAT, "config", _cfg("mock"))
    monkeypatch.setattr(scal_app, "GEMINI_KEY_POOL", ["AIzaSy-real-looking-key"])
    monkeypatch.setattr(scal_app, "_private_db_reachable", lambda: True)
    with pytest.raises(RuntimeError, match="(?i)embedding"):
        scal_app.assert_no_cloud_llm_with_private_db()


def test_reachability_is_the_live_pool_not_the_env_string(monkeypatch):
    monkeypatch.setattr(scal_app, "_PG_AVAILABLE", True)
    assert scal_app._private_db_reachable() is True
    monkeypatch.setattr(scal_app, "_PG_AVAILABLE", False)
    assert scal_app._private_db_reachable() is False


def test_invariant_is_wired_into_startup(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(scal_app.CHAT, "config", _cfg("nvidia"))
    monkeypatch.setattr(scal_app, "_private_db_reachable", lambda: True)
    with pytest.raises(RuntimeError, match="(?i)cloud"):
        with TestClient(scal_app.app):
            pass


def test_embedding_without_a_key_makes_no_call(monkeypatch):
    """No key → no embedding, and no socket. (DUMMY_KEY used to be sent to Google.)"""
    def boom():
        raise AssertionError("embed client must not be built without a key")
    monkeypatch.setattr(scal_app, "_get_embed_client", boom)
    assert scal_app.KnowledgeBase._embed("porosity") is None
