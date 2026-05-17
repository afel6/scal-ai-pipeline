import pytest
import os
import sys

# Add project root to path so test imports resolve correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
