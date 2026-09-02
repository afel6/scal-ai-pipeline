"""C2 item 1.1 — the tool-call ledger `sid` binding and the gate's fail direction.

`_tls.current_session_id` was bound only inside the two HTTP routes; `chat()`
itself never bound it, so any in-process caller recorded ledger rows under the
shared "" bucket. The gate did `sid or ""` on lookup, so a gate consulted with
an empty sid read that process-global bucket — where a stale success by tool
name from any unbound context would back a fabricated value: silent pass-through.

Pinned here: (1) an unresolvable sid means NO backing — strip, regardless of
what the "" bucket holds; (2) rows recorded with no sid are not retained;
(3) every execution context binds the sid where the tools actually run:
in-process chat(), POST /api/chat, GET /api/chat/stream.
"""
import pytest
from fastapi.testclient import TestClient

import app as scal_app

SID = "c2-sid-bind"


@pytest.fixture(autouse=True)
def _clean():
    scal_app.reset_tool_call_ledger("")
    scal_app.reset_tool_call_ledger(SID)
    scal_app._tls.current_session_id = None
    yield
    scal_app.reset_tool_call_ledger("")
    scal_app.reset_tool_call_ledger(SID)


# --- fail-closed on an unresolvable sid -----------------------------------

def test_gate_strips_with_empty_sid_even_if_unbound_bucket_has_a_success():
    # Poison the shared bucket the way an unbound context used to.
    scal_app.record_tool_call("", "fit_petrophysical_curve", "success", {"model": "ri"},
                              sorted(scal_app._GATED_PARAMETERS))
    text = "The fitted saturation exponent n is 1.987."
    gated = scal_app.enforce_citation_gate(text, "")
    assert "1.987" not in gated
    assert "[unverified" in gated


def test_gate_strips_with_none_sid():
    scal_app.record_tool_call("", "fit_petrophysical_curve", "success", {}, ["n"])
    gated = scal_app.enforce_citation_gate("The Archie exponent n = 2.140", None)
    assert "2.140" not in gated and "[unverified" in gated


def test_record_with_empty_sid_is_not_retained():
    scal_app.record_tool_call("", "fit_petrophysical_curve", "success", {}, ["n"])
    assert scal_app.get_tool_call_records("") == []
    assert scal_app.get_tool_call_records(None) == []


# --- every context binds the sid where tools run ---------------------------

class _Capture:
    """Stub provider: records the sid visible in the thread that would run tools."""
    def __init__(self):
        self.seen = []

    def __call__(self, messages_data, system_instruction, temperature, want_tools, max_tokens=4096):
        self.seen.append(getattr(scal_app._tls, "current_session_id", None))
        return scal_app._ChatResponse([scal_app._ChatPart(text="ok — no fit reported")], None)


def test_in_process_chat_binds_sid(monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(scal_app, "_chat_generate", cap)
    scal_app.assistant.chat([], "hello", stream=False, sid=SID, email="test@prc.local")
    assert cap.seen and all(s == SID for s in cap.seen), cap.seen


def test_post_api_chat_binds_sid(monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(scal_app, "_chat_generate", cap)
    client = TestClient(scal_app.app)
    r = client.post("/api/chat", data={"message": "hello", "session_id": SID,
                                       "user_email": "test@prc.local"})
    assert r.status_code == 200, r.text
    assert cap.seen and all(s == SID for s in cap.seen), cap.seen


def test_get_api_chat_stream_binds_sid(monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(scal_app, "_chat_generate", cap)
    client = TestClient(scal_app.app)
    r = client.get("/api/chat/stream", params={"message": "hello", "session_id": SID,
                                               "user_email": "test@prc.local"})
    assert r.status_code == 200, r.text[:200]
    _ = r.text  # drain the SSE stream so the worker completes
    assert cap.seen and all(s == SID for s in cap.seen), cap.seen
