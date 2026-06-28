import os
import sys

import pytest

# Add project root to path so test imports resolve correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _has_usable_gemini_key() -> bool:
    """True only when a real (non-placeholder) Gemini key is available.

    CI holds no secret, so this returns False there. Locally, app.py loads keys
    from .env via load_dotenv(), so this returns True and the real Genkit stack
    is used unchanged.
    """
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key and key != "DUMMY_KEY":
        return True
    # app.py also resolves keys from .env; sniff the file without importing app
    # (importing app is exactly what we're trying to make safe).
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY") and "=" in line:
                    val = line.split("=", 1)[1].strip().strip("\"'")
                    if val and val != "DUMMY_KEY":
                        return True
    except OSError:
        pass
    return False


# ──────────────────────────────────────────────────────────────────────────────
# CI safety shim — neutralize the live Gemini call that app.py makes at IMPORT
# time.
#
# app.py line ~2085 runs `ai = Genkit(plugins=[GoogleAI(api_key=...)], ...)` at
# module level. Constructing Genkit eagerly initializes the GoogleAI plugin,
# which calls the live Gemini API to register models. With no valid key (CI has
# no secret) this raises `google.genai.errors.ClientError: 400 API_KEY_INVALID`
# *during collection*, which aborts the ENTIRE pytest session before any test
# runs — so every test that does `from app import ...` errors out in CI.
#
# We replace genkit.ai.Genkit with an offline identity-decorator stub BEFORE any
# test module imports app. This only triggers when no usable key is present
# (i.e. CI); locally, with a real key in .env, the real Genkit stack is used
# untouched. The app-importing tests only exercise non-LLM helpers
# (sanitize_filename, verify_file_signature, calculate_derived_value,
# process_large_file_stream, the FastAPI app object, telemetry auth, etc.), none
# of which need the real Genkit model registry.
#
# NOTE: This is a CI-safety shim, not a fix. The underlying issue — app.py
# performing a network call at import time — lives in app.py and is out of scope
# to edit here. See the task report.
# ──────────────────────────────────────────────────────────────────────────────

if not _has_usable_gemini_key():
    try:
        import genkit.ai as _genkit_ai

        def _identity_decorator(*_args, **_kwargs):
            # Supports both @ai.tool(...) and @ai.flow(...): returns a decorator
            # that returns the decorated function unchanged.
            def _wrap(fn=None, *_a, **_k):
                return fn

            return _wrap

        class _StubGenkit:
            """Minimal offline stand-in for genkit.ai.Genkit (no network)."""

            def __init__(self, *_args, **_kwargs):
                self.registry = None

            def __getattr__(self, _name):
                # Any attribute (tool, flow, generate, ...) resolves to a no-op
                # decorator factory so module-level decorators still import.
                return _identity_decorator

        _genkit_ai.Genkit = _StubGenkit
    except Exception:
        # If genkit isn't importable for some reason, let the real import path
        # surface its own error rather than masking it here.
        pass


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

