"""D0 — no outbound network call may be attempted during a test run.

The guard sits on the socket layer (socket.socket.connect / connect_ex), not on
any library's intent: every Python HTTP client, SDK and stream ends up there.
It is armed at conftest import — before any application module is imported —
so import-time connections are caught too. A non-loopback connect raises
EgressBlocked and is recorded; the autouse fixture in conftest fails the test
that caused it even when the calling code swallowed the exception.

Known limit (stated, not hidden): libpq (psycopg2) connects from C and never
touches Python sockets, so Postgres is covered by the config assertion in
conftest (DATABASE_URL blank under tests) rather than by this guard.
"""
import socket

import pytest

import egress_guard


def test_guard_is_armed_before_any_test_runs():
    assert egress_guard.ARMED is True


def test_public_address_is_blocked_at_the_socket_and_recorded():
    n = len(egress_guard.ATTEMPTS)
    with pytest.raises(egress_guard.EgressBlocked):
        socket.create_connection(("192.0.2.1", 80), timeout=1)   # TEST-NET-1, never routable
    assert egress_guard.ATTEMPTS[n:] == ["192.0.2.1:80"]
    del egress_guard.ATTEMPTS[n:]        # this test tripped it on purpose


def test_hostname_is_blocked_without_resolving_it():
    n = len(egress_guard.ATTEMPTS)
    with pytest.raises(egress_guard.EgressBlocked):
        socket.socket().connect(("generativelanguage.googleapis.com", 443))
    assert egress_guard.ATTEMPTS[n:] == ["generativelanguage.googleapis.com:443"]
    del egress_guard.ATTEMPTS[n:]


def test_loopback_reaches_the_real_socket():
    n = len(egress_guard.ATTEMPTS)
    with pytest.raises(OSError) as ei:                             # refused, not blocked
        socket.create_connection(("127.0.0.1", 1), timeout=1)
    assert not isinstance(ei.value, egress_guard.EgressBlocked)
    assert len(egress_guard.ATTEMPTS) == n


def test_no_egress_happened_during_import_and_collection():
    """`import app` (Postgres pool, SDK clients, HF hub) must be offline."""
    assert egress_guard.COLLECTION_ATTEMPTS == []


def test_app_runs_on_the_mock_provider_with_no_private_db_under_tests():
    import app
    assert app.CHAT.config.provider == "mock"
    assert app.DATABASE_URL == "" and app._PG_AVAILABLE is False
    assert app.GEMINI_KEY_POOL == ["DUMMY_KEY"]
