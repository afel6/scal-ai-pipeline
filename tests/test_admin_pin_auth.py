"""B1 (scal) — the real auth path works with a real token, and there is no
deploy-time skip-auth branch.

These tests turn OFF the pytest bypass (is_testing) so they exercise the actual
production auth path, and issue a REAL token rather than overriding the
dependency. They also pin the fail-closed rule: an empty ADMIN_PIN must NOT
open every route (the old `if not ADMIN_PIN: return True` was a deployable
backdoor — deploy without the PIN and auth was wide open).
"""
import pytest
from fastapi.testclient import TestClient

import app as scal_app
from app import app, verify_user_or_admin


@pytest.fixture()
def real_auth_client(monkeypatch):
    # Exercise the production auth path: no pytest bypass, no dependency override.
    monkeypatch.setattr(scal_app, "is_testing", lambda: False)
    monkeypatch.setattr(scal_app, "ADMIN_PIN", "b1-known-admin-pin")
    saved = app.dependency_overrides.pop(verify_user_or_admin, None)
    try:
        yield TestClient(app)
    finally:
        if saved is not None:
            app.dependency_overrides[verify_user_or_admin] = saved


def test_depends_route_rejects_without_token(real_auth_client):
    resp = real_auth_client.post("/api/clear-session", data={"session_id": "b1-x"})
    assert resp.status_code == 401, resp.text


def test_depends_route_accepts_real_admin_token(real_auth_client, monkeypatch):
    import time
    token = "b1-real-admin-token"
    monkeypatch.setitem(scal_app._ADMIN_TOKENS, token, time.time() + 900)
    resp = real_auth_client.post(
        "/api/clear-session", data={"session_id": "b1-x"},
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code != 401, resp.text


def test_empty_admin_pin_is_fail_closed(real_auth_client, monkeypatch):
    # The removed backdoor: an empty ADMIN_PIN must deny, not allow.
    monkeypatch.setattr(scal_app, "ADMIN_PIN", "")
    resp = real_auth_client.post("/api/clear-session", data={"session_id": "b1-x"})
    assert resp.status_code == 401, (
        "empty ADMIN_PIN must fail closed, not open every route")
