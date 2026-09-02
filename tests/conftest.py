"""Test-run environment for scal (D0 air-gap).

Order matters: the egress guard is armed — and the process pinned offline
(mock LLM providers, DATABASE_URL blank so tests never touch the private
Postgres, every credential name from .env present but empty) — BEFORE any
application module is imported, so import-time connections are caught too.
Set ALLOW_EGRESS=1 only for the quarantined live protocols.
"""
import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

import egress_guard  # noqa: E402

egress_guard.arm(os.path.join(_ROOT, ".env"))


def pytest_collection_finish(session):
    egress_guard.snapshot_collection()


@pytest.fixture(autouse=True)
def _fail_on_egress():
    """Fail the test that attempted an outbound call — even one that swallowed
    the EgressBlocked exception (broad `except Exception` around an SDK call)."""
    before = len(egress_guard.ATTEMPTS)
    yield
    new = egress_guard.ATTEMPTS[before:]
    if new:
        pytest.fail(f"outbound network call attempted during this test (socket layer): {new}")


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """
    Lightweight DB setup — only runs if app is importable.
    Physics, prompt, vision, and stress tests don't touch the DB at all;
    this fixture is kept only for test_hviel_behavioral.py which is run
    separately and excluded from the standard CI suite.
    """
    try:
        from app import init_db
        init_db()
    except Exception:
        pass  # DB unavailable is fine for unit tests


@pytest.fixture(scope="session", autouse=True)
def override_auth():
    from app import app, verify_user_or_admin
    app.dependency_overrides[verify_user_or_admin] = lambda: True
    yield
    app.dependency_overrides.pop(verify_user_or_admin, None)
