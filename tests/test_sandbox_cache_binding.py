"""D2 corpus finding — a corrected (clamped) sandbox fit is never bound into
the session cache's labeled values.

The sandbox dispatch used to write the clamped parameters (Archie n=1.5 at the
window floor; Brooks-Corey exponents likewise) into labeled_values regardless
of `corrected`, so a `{{val:n}}` provenance token could render the clamp bound
as `1.500 · CACHED · HIGH`. Only an uncorrected fit is bound.
"""
import pytest

import app
import physics_sandbox

SID = "d2-sandbox-bind"


@pytest.fixture(autouse=True)
def _session():
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE[SID] = {"labeled_values": {"n": 1.85}}
    app._tls.current_session_id = SID
    yield
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE.pop(SID, None)
    app._tls.current_session_id = None


def _labeled():
    with app.SESSION_DATA_CACHE_LOCK:
        return dict(app.SESSION_DATA_CACHE[SID]["labeled_values"])


def _run(tool, args):
    call = app._ChatFuncCall(tool, args)
    return list(app.assistant._execute_tool(call))[-1]


@pytest.mark.parametrize("tool,args,params,keys", [
    ("sandbox_fit_archie", {"x": [0.9, 0.5], "y": [1.1, 3.0], "model_type": "RI"},
     {"n": 1.5, "b": 1.0}, ("n", "b")),
    ("sandbox_fit_brooks_corey", {"sw": [0.2, 0.8], "krw": [0.0, 0.5], "kro": [0.9, 0.0],
                                  "swi": 0.2, "sor": 0.2}, {"nw": 1.0, "no": 1.0, "Swi": 0.2, "Sor": 0.2},
     ("nw", "no")),
])
def test_corrected_fit_is_not_bound(monkeypatch, tool, args, params, keys):
    monkeypatch.setattr(physics_sandbox, "run_sandboxed",
                        lambda source, inputs=None: {"parameters": params, "corrected": True,
                                                     "coordinates": {}, "health": {}})
    _run(tool, args)
    labeled = _labeled()
    assert labeled == {"n": 1.85}, labeled                 # untouched: no key from the clamped fit
    assert not any(k in labeled for k in keys if k != "n")


def test_uncorrected_archie_fit_is_bound(monkeypatch):
    monkeypatch.setattr(physics_sandbox, "run_sandboxed",
                        lambda source, inputs=None: {"parameters": {"n": 2.1, "b": 1.0}, "corrected": False,
                                                     "coordinates": {}, "health": {}})
    _run("sandbox_fit_archie", {"x": [0.9, 0.5], "y": [1.1, 3.0], "model_type": "RI"})
    assert _labeled()["n"] == pytest.approx(2.1)
