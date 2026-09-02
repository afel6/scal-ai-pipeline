"""Pre-C1 item 2 — the scal-side open routes are closed, and /api/scal/calibrate
bounds its input.

C1 makes scal the service receiving all delegated traffic, so the routes B left
open on the scal side (`/api/kb/status`, `/api/skills/list`, `/api/scal/calibrate`)
move to the front line. Each now requires authentication (scal's existing
verify_user_or_admin — no second credential), and calibrate rejects an oversized
array at the request boundary before any fitting runs.

Auth is exercised on the real production path: pytest bypass off, real admin
token, override popped.
"""
import time

import pytest
from fastapi.testclient import TestClient

import app as scal_app
from app import app, verify_user_or_admin


@pytest.fixture()
def real_auth_client(monkeypatch):
    monkeypatch.setattr(scal_app, "is_testing", lambda: False)
    monkeypatch.setattr(scal_app, "ADMIN_PIN", "item2-admin-pin")
    saved = app.dependency_overrides.pop(verify_user_or_admin, None)
    try:
        yield TestClient(app)
    finally:
        if saved is not None:
            app.dependency_overrides[verify_user_or_admin] = saved


def _admin_headers(monkeypatch):
    token = "item2-admin-token"
    monkeypatch.setitem(scal_app._ADMIN_TOKENS, token, time.time() + 900)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("method,path,body", [
    ("GET",  "/api/kb/status", None),
    ("GET",  "/api/skills/list", None),
    ("POST", "/api/scal/calibrate", {"porosity": [0.2, 0.25], "formation_factor": [20.0, 12.0]}),
])
def test_open_scal_route_rejects_without_token(real_auth_client, method, path, body):
    r = real_auth_client.get(path) if method == "GET" else real_auth_client.post(path, json=body or {})
    assert r.status_code == 401, f"{method} {path} -> {r.status_code}: {r.text[:200]}"


@pytest.mark.parametrize("method,path,body", [
    ("GET",  "/api/kb/status", None),
    ("GET",  "/api/skills/list", None),
    ("POST", "/api/scal/calibrate", {"porosity": [0.2, 0.25], "formation_factor": [20.0, 12.0]}),
])
def test_open_scal_route_accepts_with_token(real_auth_client, monkeypatch, method, path, body):
    h = _admin_headers(monkeypatch)
    r = real_auth_client.get(path, headers=h) if method == "GET" else real_auth_client.post(path, json=body or {}, headers=h)
    assert r.status_code != 401, f"{method} {path} rejected a valid token ({r.status_code})"


def test_calibrate_oversized_array_rejected_before_compute(real_auth_client, monkeypatch):
    h = _admin_headers(monkeypatch)
    big = [0.2] * 5000
    with pytest.MonkeyPatch.context() as mp:
        # If validation lets the oversized body through, this would run — assert it does not.
        import numpy as np
        called = {"n": 0}
        orig = np.polyfit
        mp.setattr(np, "polyfit", lambda *a, **k: (called.__setitem__("n", called["n"] + 1), orig(*a, **k))[1])
        r = real_auth_client.post("/api/scal/calibrate",
                                  json={"porosity": big, "formation_factor": big}, headers=h)
    assert r.status_code == 422, r.text
    assert called["n"] == 0, "compute ran on an oversized array — bound not enforced at the boundary"


def test_calibrate_within_bounds_still_runs(real_auth_client, monkeypatch):
    h = _admin_headers(monkeypatch)
    r = real_auth_client.post("/api/scal/calibrate",
                              json={"porosity": [0.30, 0.25, 0.20, 0.15], "formation_factor": [11.0, 16.0, 25.0, 44.0]},
                              headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "archie"
