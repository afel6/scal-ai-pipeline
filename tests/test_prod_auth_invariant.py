"""Pre-C1 item 4 — the pytest auth bypass must be an enforced invariant.

`is_testing()` short-circuits verify_user_or_admin, and the analysis that it is
not production-reachable (pytest-gated, and the deployable `if not ADMIN_PIN`
form is gone) is sound — but it is an argument, not a guarantee. This turns it
into one: under a real ASGI server (uvicorn/gunicorn) the process hard-fails if
is_testing() is somehow true (e.g. PYTEST_CURRENT_TEST leaked into the env, or
is_testing() gets weakened later).

Both directions are tested: the assertion fires when the server context is
forced, and stays silent under pytest (where it must never fire).
"""
import pytest

import app as scal_app


def test_invariant_fires_when_server_context_forced(monkeypatch):
    monkeypatch.setattr(scal_app, "is_testing", lambda: True)
    with pytest.raises(RuntimeError, match="(?i)is_testing.*production|auth bypass"):
        scal_app.assert_auth_bypass_disabled_in_production(force=True)


def test_invariant_fires_when_launched_as_uvicorn(monkeypatch):
    monkeypatch.setattr(scal_app, "is_testing", lambda: True)
    monkeypatch.setattr(scal_app.sys, "argv", ["/usr/local/bin/uvicorn", "app:app"])
    with pytest.raises(RuntimeError):
        scal_app.assert_auth_bypass_disabled_in_production()


def test_invariant_silent_under_pytest():
    # Real pytest run: is_testing() is True, but the launcher is pytest, not a
    # server — the guard must NOT fire, or it would break the whole suite.
    assert scal_app.is_testing() is True
    scal_app.assert_auth_bypass_disabled_in_production()  # must not raise


def test_invariant_silent_when_not_testing_even_under_server(monkeypatch):
    monkeypatch.setattr(scal_app, "is_testing", lambda: False)
    monkeypatch.setattr(scal_app.sys, "argv", ["/usr/local/bin/uvicorn", "app:app"])
    scal_app.assert_auth_bypass_disabled_in_production()  # must not raise


def test_invariant_fires_under_unlisted_launcher(monkeypatch):
    """C1 item 1.3 — the inverted, fail-closed primary check.

    The old detection enumerated server shapes (uvicorn/gunicorn argv,
    SERVER_SOFTWARE); any launcher not on that list silently passed. Inverted:
    is_testing() true while pytest is absent from sys.modules is the hard-fail
    condition — pytest actually running is the only positive, reliable signal.
    This test uses a launcher on nobody's list (hypercorn) with a leaked
    PYTEST_CURRENT_TEST: the old enumeration would pass it; the inversion fires.
    """
    import sys as real_sys
    monkeypatch.setattr(scal_app.sys, "argv", ["/usr/local/bin/hypercorn", "app:app"])
    monkeypatch.delenv("SERVER_SOFTWARE", raising=False)
    # Simulate the leak: PYTEST_CURRENT_TEST present (is_testing() -> True) but
    # pytest itself not running in this process.
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "leaked::from::env")
    monkeypatch.delitem(real_sys.modules, "pytest", raising=False)
    try:
        with pytest.raises(RuntimeError):
            scal_app.assert_auth_bypass_disabled_in_production()
    finally:
        real_sys.modules.setdefault("pytest", pytest)
