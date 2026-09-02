"""Shared setup for the BASWE evaluation suite.

Puts the repo root on sys.path (so app/grader/physics modules import), arms
the D0 egress guard (offline pin: mock provider, no private database, empty
credential names) BEFORE the app is imported, then loads .env to mirror
app.py's key resolution — load_dotenv never overrides the pinned names. The
Layer-1 live runs set ALLOW_EGRESS=1 (guard and pin skipped) and MUST run with
DATABASE_URL blank: a cloud provider with the private database reachable is a
startup hard-fail (assert_no_cloud_llm_with_private_db).
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import egress_guard  # noqa: E402

egress_guard.arm(str(REPO_ROOT / ".env"))

# Mirror app.py: keys may live in .env rather than the shell environment.
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass


def pytest_collection_finish(session):
    egress_guard.snapshot_collection()


@pytest.fixture(autouse=True)
def _fail_on_egress():
    before = len(egress_guard.ATTEMPTS)
    yield
    new = egress_guard.ATTEMPTS[before:]
    if new:
        pytest.fail(f"outbound network call attempted during this test (socket layer): {new}")


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient over the real app (auth auto-bypassed under pytest)."""
    from fastapi.testclient import TestClient
    from app import app as fastapi_app

    with TestClient(fastapi_app) as c:
        yield c
