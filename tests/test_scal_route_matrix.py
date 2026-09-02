"""Pre-C1 item 3 — every scal /api route must carry authentication.

B1 built this structural guard for pvt only; had it existed on scal it would
have enumerated the open routes instead of them being found by hand. It walks
every registered scal route and fails the suite if an /api route is neither
covered by an auth dependency (verify_user_or_admin / verify_admin / the
_bearer variant) nor by an inline / shared-secret auth check — with an explicit
allowlist for the genuinely public routes, so an exemption is a deliberate line.

scal authenticates three ways (Depends, an inline verify_*() call, and
form/header shared-secret checks), so the guard accepts any of them. The second
test proves the guard has teeth: a deliberately unprotected /api route is
flagged.
"""
import inspect

from fastapi import FastAPI
from starlette.routing import Route

import app as scal_app

# Genuinely public /api routes: the two login entry points. /health and the SPA
# catch-all are not under /api and are out of scope by construction.
PUBLIC_API_ROUTES = {"/api/auth", "/api/admin/auth"}

# Any of these appearing in a route's dependency tree or handler source counts
# as an auth check. Kept tight so a stray mention is unlikely to mask a gap.
_SRC_MARKERS = ("verify_user_or_admin", "verify_admin", "compare_digest",
                "KB_INGEST_SECRET", "X-Ingest-Secret", "X-Admin-Pin")


def _dep_call_names(route):
    names = []
    def walk(dep):
        call = getattr(dep, "call", None)
        if call is not None:
            names.append(getattr(call, "__name__", ""))
        for sub in getattr(dep, "dependencies", []):
            walk(sub)
    if hasattr(route, "dependant"):
        walk(route.dependant)
    return names


def _route_is_protected(route) -> bool:
    names = _dep_call_names(route)
    if any("verify_user_or_admin" in n or "verify_admin" in n for n in names):
        return True
    try:
        src = inspect.getsource(route.endpoint)
    except (OSError, TypeError):
        src = ""
    return any(m in src for m in _SRC_MARKERS)


def _api_offenders(routes):
    offenders = []
    for r in routes:
        if not isinstance(r, Route):
            continue
        if not r.path.startswith("/api/"):
            continue  # /health, SPA catch-all, static mount — public by construction
        if r.path in PUBLIC_API_ROUTES:
            continue
        if not _route_is_protected(r):
            methods = ",".join(sorted(m for m in (r.methods or set()) if m != "HEAD"))
            offenders.append(f"{methods} {r.path}")
    return offenders


def test_every_scal_api_route_is_authenticated():
    offenders = _api_offenders(scal_app.app.routes)
    assert not offenders, "scal /api routes missing auth: " + ", ".join(sorted(offenders))


def test_guard_flags_an_unprotected_route():
    """Teeth: an /api route with no auth must be caught (the RED this guard exists to catch)."""
    probe = FastAPI()

    @probe.get("/api/__unprotected_probe__")
    def _open():                       # no dependency, no inline/secret check
        return {"ok": True}

    @probe.get("/api/__protected_probe__")
    def _closed(auth: bool = None):    # source carries an auth marker
        verify_user_or_admin = None    # noqa: F841 — marker for the detector
        return {"ok": True}

    offenders = _api_offenders(probe.routes)
    assert any("__unprotected_probe__" in o for o in offenders), offenders
    assert not any("__protected_probe__" in o for o in offenders), offenders
