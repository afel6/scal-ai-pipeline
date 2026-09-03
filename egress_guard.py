"""Socket-level egress guard for test runs (D0 air-gap).

Call `arm(dotenv_path)` from a conftest BEFORE any application import. It
(1) pins the process to an offline configuration — mock LLM providers, no
private database, local embedders in offline mode, every credential name from
.env present but EMPTY so a later load_dotenv(override=False) cannot repopulate
it — and (2) patches socket.socket.connect / connect_ex so that every connect()
to a non-loopback address raises EgressBlocked and is recorded in ATTEMPTS.
The conftest's autouse fixture fails the test that made the attempt (even if
the caller swallowed the exception); COLLECTION_ATTEMPTS captures anything that
happened at import/collection time.

Loopback (127.0.0.0/8, ::1, "localhost") and AF_UNIX pass through to the real
socket, so a local Postgres, a local Ollama probe and the in-process TestClient
keep working. Any hostname is treated as egress without resolving it.

Opt-out — for the quarantined live protocols only — ALLOW_EGRESS=1 (then
nothing here is applied and ARMED stays False).

Known limit, stated not hidden: libpq (psycopg2) connects from C and never
reaches Python sockets; Postgres targets are asserted by configuration
(DATABASE_URL blank / PG_HOST loopback) rather than by this guard.

Both hub repos carry a copy of this file (scal-ai-pipeline/egress_guard.py and
pvt-ai-pipeline/tests/egress_guard.py).
"""
from __future__ import annotations

import ipaddress
import os
import socket
from typing import List, Optional


class EgressBlocked(RuntimeError):
    """Raised at the socket layer for any non-loopback connect during tests."""


ATTEMPTS: List[str] = []
COLLECTION_ATTEMPTS: List[str] = []
ARMED = False

_ORIG_CONNECT = socket.socket.connect
_ORIG_CONNECT_EX = socket.socket.connect_ex
_CREDENTIAL_TOKENS = ("API_KEY", "KEY_POOL")


def _is_local(address) -> bool:
    if not isinstance(address, tuple) or not address:
        return True                                   # AF_UNIX path
    host = str(address[0]).split("%", 1)[0]
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False                                  # a hostname is egress; never resolve it


def _describe(address) -> str:
    if isinstance(address, tuple) and len(address) >= 2:
        return f"{address[0]}:{address[1]}"
    return repr(address)


def _guarded(orig):
    def connect(self, address, *args, **kwargs):
        if not _is_local(address):
            ATTEMPTS.append(_describe(address))
            raise EgressBlocked(
                f"outbound network call blocked during tests: {_describe(address)}")
        return orig(self, address, *args, **kwargs)
    return connect


def pin_offline_env(dotenv_path: Optional[str]) -> None:
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["AGENT_LLM_PROVIDER"] = "mock"
    os.environ["DATABASE_URL"] = ""                   # SQLite store, never the private Postgres
    os.environ["HF_HUB_OFFLINE"] = "1"                # local embedders never phone home
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["GEMINI_API_KEY"] = "DUMMY_KEY"
    if dotenv_path and os.path.exists(dotenv_path):
        try:
            from dotenv import dotenv_values
            names = list(dotenv_values(dotenv_path))
        except Exception:                             # noqa: BLE001
            names = []
        for name in names:
            if any(t in name for t in _CREDENTIAL_TOKENS) and name != "GEMINI_API_KEY":
                os.environ[name] = ""


def arm(dotenv_path: Optional[str] = None) -> None:
    global ARMED
    if os.environ.get("ALLOW_EGRESS") == "1":
        return
    pin_offline_env(dotenv_path)
    if not ARMED:
        socket.socket.connect = _guarded(_ORIG_CONNECT)
        socket.socket.connect_ex = _guarded(_ORIG_CONNECT_EX)
        ARMED = True


def snapshot_collection() -> None:
    COLLECTION_ATTEMPTS[:] = list(ATTEMPTS)
