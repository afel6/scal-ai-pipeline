"""Pre-C1 item 1 — a plot must never label a curve with an unfitted parameter.

B0.1 run 6 rendered `RI Archie  n=1.500` as a plot series label in a run whose
true n was 1.2, whose fit could never succeed, and whose prose the citation gate
had correctly stripped to `[unverified …]`. 1.500 is the exact lower bound of the
Archie window: `PhysicsSandbox.fit_archie` clamps a free fit that escapes the
physical range to the bound and returns it with `corrected=True`, and the
sandbox_fit_archie plot formatter (app.py) printed `n={n_val:.3f}` regardless.

These tests force the fit to fail and assert directly on the rendered label:
a clamped/corrected parameter is never presented as fitted (A3 provenance
pattern). A clean in-range fit still shows its number.
"""
import json
import re

import app
from physics_sandbox import PhysicsSandbox

SW = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]


def _payload_plot(payload: str) -> dict:
    return json.loads(payload.split("__PRC_PLOT__", 1)[1].strip())


def test_clamped_archie_ri_not_labelled_as_fitted():
    # true n = 1.2 (below the 1.5 floor) -> clamped to 1.5, corrected=True
    ri = [round(s ** -1.2, 5) for s in SW]
    fit = PhysicsSandbox().fit_archie(SW, ri, "RI")
    assert fit["corrected"] is True and fit["parameters"]["n"] == 1.5

    payload = app.assistant._format_tool_response(
        "sandbox_fit_archie", {"model_type": "RI", "sample_name": "B1-plot"},
        json.dumps(fit))

    # No rendered surface may present the clamped exponent as a fitted result.
    assert "n=1.500" not in payload and "n=1.5" not in payload.replace(" ", "")
    plot = _payload_plot(payload)
    labels = [c["name"] for c in plot["curves"]]
    assert not any(re.search(r"n=\d", lbl) for lbl in labels), labels
    assert plot["metadata"]["archie"]["fitted"] is False
    assert plot["metadata"]["archie"]["n"] is None


def test_clean_archie_ri_still_shows_fitted_n():
    # true n = 2.0 (in range) -> a genuine fit, not corrected
    ri = [round(s ** -2.0, 5) for s in SW]
    fit = PhysicsSandbox().fit_archie(SW, ri, "RI")
    assert fit["corrected"] is False

    payload = app.assistant._format_tool_response(
        "sandbox_fit_archie", {"model_type": "RI", "sample_name": "B1-plot"},
        json.dumps(fit))
    assert re.search(r"RI Archie\s+n=2\.0", payload), payload[:400]
    plot = _payload_plot(payload)
    assert plot["metadata"]["archie"]["fitted"] is True
    assert plot["metadata"]["archie"]["n"] == 2.0


def test_corrected_sandbox_label_is_load_bearing_regression_pin():
    """C2 item 1.3 — pins the guard the model routes around.

    In 2 of 13 measured live runs the model retried through sandbox_fit_archie
    after the cache path refused it (C1 2.4). That path is safe ONLY because a
    corrected fit is labelled unfitted. This pins every surface of the payload:
    curve labels, metadata.archie numeric fields, and the payload's JSON —
    no numeric parameter is presented as fitted anywhere.
    """
    ri = [round(s ** -1.2, 5) for s in SW]           # true n=1.2 -> clamped to 1.5
    fit = PhysicsSandbox().fit_archie(SW, ri, "RI")
    assert fit["corrected"] is True
    payload = app.assistant._format_tool_response(
        "sandbox_fit_archie", {"model_type": "RI", "sample_name": "pin"}, json.dumps(fit))
    plot = _payload_plot(payload)
    # 1) labels: no `<param>=<number>` on any curve
    for lbl in (c["name"] for c in plot["curves"]):
        assert not re.search(r"\b(n|m|a|b)\s*=\s*\d", lbl), lbl
    # 2) metadata: numeric parameter fields are null, fitted is False
    meta = plot["metadata"]["archie"]
    assert meta["fitted"] is False
    assert all(meta.get(k) is None for k in ("n", "m", "a"))
    # 3) payload JSON: no numeric "n"/"m"/"a" value anywhere under archie
    assert not re.search(r'"(?:n|m|a)":\s*\d', json.dumps(meta))
    # The only numbers permitted are inside the provenance note, which names the
    # REJECTED free fit ("Free fit out of bounds (... n=1.200)") — explicitly not
    # a fitted result.
    assert "out of bounds" in meta["note"]


def test_clamped_archie_ff_not_labelled_as_fitted():
    # true m = 3.0 (above the 2.5 ceiling) -> clamped, corrected=True
    phi = [0.30, 0.25, 0.22, 0.18, 0.15, 0.12, 0.09]
    ff = [round(p ** -3.0, 5) for p in phi]
    fit = PhysicsSandbox().fit_archie(phi, ff, "FF")
    assert fit["corrected"] is True

    payload = app.assistant._format_tool_response(
        "sandbox_fit_archie", {"model_type": "FF", "sample_name": "B1-plot"},
        json.dumps(fit))
    plot = _payload_plot(payload)
    labels = [c["name"] for c in plot["curves"]]
    assert not any(re.search(r"[ma]=\d", lbl) for lbl in labels), labels
    assert plot["metadata"]["archie"]["fitted"] is False
