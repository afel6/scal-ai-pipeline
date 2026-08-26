"""Shared setup for the BASWE evaluation suite.

Puts the repo root on sys.path (so app/grader/physics modules import) and
loads .env to mirror app.py's key resolution. The TestClient fixture lives
here; all other eval helpers are in test_baswe_eval.py.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Mirror app.py: keys may live in .env rather than the shell environment.
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient over the real app (auth auto-bypassed under pytest)."""
    from fastapi.testclient import TestClient
    from app import app as fastapi_app

    with TestClient(fastapi_app) as c:
        yield c
