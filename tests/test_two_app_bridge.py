"""D1 — both hub apps import in ONE process and the real bridge runs end to end.

Until D1 both repos owned a top-level `src` package: scal's `app` imported next
to the hub silently resolved `src.rag.router` to the hub's `src` (ImportError
swallowed → "routing failed"), and no in-process two-app test was possible.
scal's package is now `hviel`. This test drives the hub's real bridge
(`t_scal_analyze` → httpx.Client) into the real scal FastAPI app with the
scal-side model scripted on the mock. It lives in the scal repo because the
scal environment carries both apps' dependencies (test_file_isolation does the
same import); it skips when the sibling checkout or the hub's deps are absent.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PVT = ROOT.parent / "pvt-ai-pipeline"
pytestmark = pytest.mark.skipif(not (PVT / "src" / "api" / "app.py").exists(),
                                reason="sibling pvt-ai-pipeline checkout not present")

QUESTION = "In one paragraph, what does the Amott-Harvey wettability index measure?"
SCAL_REPLY = ("The Amott-Harvey index combines the water and oil displacement ratios; "
              "sample D1-1 reads [unverified - no successful fit produced this value] for n.")
FRAMING = "SCAL pipeline reports:\n\n"


@pytest.fixture(scope="module")
def hub():
    if str(PVT) not in sys.path:
        sys.path.append(str(PVT))
    pytest.importorskip("src.api.agents", reason="hub dependencies not installed in this env")
    from src.api import agents as ag
    from src.utils.config import settings
    return ag, settings


def test_both_packages_coexist_under_their_own_names(hub):
    import hviel.rag.router as scal_router
    import src.api.app as hub_app
    assert pathlib.Path(scal_router.__file__).is_relative_to(ROOT)
    assert pathlib.Path(hub_app.__file__).is_relative_to(PVT)


def test_hviel_delegates_into_the_real_scal_app_in_process(hub, monkeypatch, caplog):
    from fastapi.testclient import TestClient
    import app as scal_app
    ag, settings = hub

    monkeypatch.setattr(scal_app, "USER_PIN", "d1-bridge-pin")
    monkeypatch.setattr(settings, "SCAL_API_PIN", "d1-bridge-pin")
    monkeypatch.setattr(settings, "SCAL_API_URL", "http://scal.local")
    ag._scal_bridge_token["value"] = None
    scal_client = TestClient(scal_app.app, base_url="http://scal.local")
    # The bridge's httpx.Client IS the scal app: no socket, no fake — the real
    # login, the real /api/chat, the real assembly path on the scal side.
    monkeypatch.setattr(ag.httpx, "Client", lambda *a, **k: scal_client)

    scal_app.CHAT.load_script(scal_app.llm_adapter.MockScript.from_dict(
        {"name": "d1-bridge", "steps": [{"assistant": SCAL_REPLY}]}))
    try:
        with caplog.at_level("INFO"):
            r = ag.AGENTS["hviel"].run(QUESTION)
    finally:
        scal_app.CHAT.load_script(None)

    assert r["trace"][0]["tool"] == "scal_analyze"
    assert r["answer"] == FRAMING + SCAL_REPLY            # byte-for-byte through both apps
    assert r.get("passthrough") is True
    # scal's own RAG router ran under its own package — no namespace collision.
    msgs = [rec.getMessage() for rec in caplog.records]
    assert any("[RAG-ROUTER] route=" in m for m in msgs), msgs[-5:]
    assert not any("routing failed" in m for m in msgs)
