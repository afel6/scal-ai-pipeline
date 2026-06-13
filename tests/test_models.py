"""Live Gemini model-availability check (integration).

This test talks to the real Gemini API to confirm the configured key can list
models on the v1beta endpoint (the version the app relies on for function
calling). It is therefore an integration test: it is skipped automatically when
no usable GEMINI_API_KEY is available (e.g. on CI, which holds no secret), and
runs only when a real key is present in the environment.

Originally this file was a top-level script with no test function, so pytest
collected 0 items.
"""

import os

import pytest


def _resolve_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    # Fall back to the app's key pool (populated from .env via load_dotenv),
    # but never treat the placeholder DUMMY_KEY as usable.
    try:
        from app import GEMINI_KEY_POOL  # noqa: WPS433 (local import is intentional)

        if GEMINI_KEY_POOL and GEMINI_KEY_POOL[0] not in ("", "DUMMY_KEY"):
            return GEMINI_KEY_POOL[0]
    except Exception:
        pass
    return ""


_KEY = _resolve_key()


@pytest.mark.integration
@pytest.mark.skipif(not _KEY, reason="No usable GEMINI_API_KEY available (live API test)")
def test_gemini_v1beta_lists_models():
    from google import genai

    client = genai.Client(api_key=_KEY, http_options={"api_version": "v1beta"})
    models = list(client.models.list())
    assert len(models) > 0, "v1beta returned no models"
    assert all(getattr(m, "name", None) for m in models)
