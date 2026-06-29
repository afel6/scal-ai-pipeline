"""Unit tests for the Autonomous Physics Sandbox (physics_sandbox.py)."""

import numpy as np
import pytest

from physics_sandbox import (
    PhysicsSandbox,
    PhysicalValidationError,
    SandboxSecurityError,
    archie_formation_factor,
    archie_resistivity_index,
    run_sandboxed,
)


@pytest.fixture
def sandbox():
    return PhysicsSandbox()


# ── synthetic lab data helpers ─────────────────────────────────────────────────

def _clean_brooks_corey(swi=0.2, sor=0.2, nw=2.5, no=3.0, krw_max=0.5, kro_max=0.9):
    sw = np.linspace(swi, 1 - sor, 25)
    se = (sw - swi) / (1 - swi - sor)
    se = np.clip(se, 1e-6, 1.0)
    krw = krw_max * se ** nw
    kro = kro_max * (1 - se) ** no
    return sw, krw, kro


# ── Brooks-Corey ───────────────────────────────────────────────────────────────

def test_brooks_corey_clean_fit_passes(sandbox):
    sw, krw, kro = _clean_brooks_corey()
    out = sandbox.fit_brooks_corey(sw, krw, kro, swi=0.2, sor=0.2,
                                   krw_max=0.5, kro_max=0.9)
    assert out["model"] == "brooks_corey"
    assert out["health"]["grade"] in {"A", "B"}
    assert out["coordinates"]["labels"] == ["Krw", "Kro"]
    assert len(out["coordinates"]["x"]) == len(out["coordinates"]["y"][0])
    assert out["corrected"] is False


def test_brooks_corey_coordinates_are_serializable(sandbox):
    sw, krw, kro = _clean_brooks_corey()
    out = sandbox.fit_brooks_corey(sw, krw, kro, swi=0.2, sor=0.2)
    import json
    json.dumps(out)  # must not raise — payload is pure JSON


def test_brooks_corey_rejects_out_of_range_saturation(sandbox):
    sw = np.array([0.2, 0.5, 1.3])  # 1.3 is non-physical
    krw = np.array([0.0, 0.2, 0.5])
    kro = np.array([0.9, 0.3, 0.0])
    with pytest.raises(PhysicalValidationError):
        sandbox.fit_brooks_corey(sw, krw, kro, swi=0.2, sor=0.2)


def test_brooks_corey_auto_corrects_noisy_crossing(sandbox):
    # Build deliberately anomalous (noisy, near-crossing) curves and confirm the
    # corrector recovers a physical, passing-grade result.
    sw, krw, kro = _clean_brooks_corey(nw=1.0, no=1.0)
    rng = np.random.default_rng(0)
    krw_noisy = np.clip(krw + rng.normal(0, 0.05, krw.size), 0, 1)
    kro_noisy = np.clip(kro + rng.normal(0, 0.05, kro.size), 0, 1)
    out = sandbox.fit_brooks_corey(sw, krw_noisy, kro_noisy, swi=0.2, sor=0.2,
                                   krw_max=0.5, kro_max=0.9)
    assert out["health"]["grade"] in {"A", "B"}


# ── Archie ─────────────────────────────────────────────────────────────────────

def test_archie_ff_fit_recovers_parameters(sandbox):
    phi = np.linspace(0.05, 0.35, 12)
    ff = archie_formation_factor(phi, a=1.0, m=2.0)
    out = sandbox.fit_archie(phi, ff, model_type="FF")
    assert out["model"] == "archie_ff"
    assert out["parameters"]["m"] == pytest.approx(2.0, abs=0.05)
    assert out["parameters"]["a"] == pytest.approx(1.0, abs=0.1)
    assert out["health"]["grade"] == "A"


def test_archie_ri_fit_recovers_n(sandbox):
    sw = np.linspace(0.2, 1.0, 12)
    ri = archie_resistivity_index(sw, b=1.0, n=2.0)
    out = sandbox.fit_archie(sw, ri, model_type="RI")
    assert out["model"] == "archie_ri"
    assert out["parameters"]["n"] == pytest.approx(2.0, abs=0.05)


def test_archie_auto_corrects_out_of_bounds_exponent(sandbox):
    # m = 3.2 is outside the physical [1.3, 2.5] window → corrector must clamp it.
    phi = np.linspace(0.05, 0.35, 12)
    ff = archie_formation_factor(phi, a=1.0, m=3.2)
    out = sandbox.fit_archie(phi, ff, model_type="FF")
    assert out["corrected"] is True
    assert 1.3 <= out["parameters"]["m"] <= 2.5
    assert out["health"]["grade"] in {"A", "B"}
    assert out["notes"]  # an explanation was recorded


def test_archie_invalid_model_type(sandbox):
    with pytest.raises(ValueError):
        sandbox.fit_archie([0.1], [10.0], model_type="ZZ")


# ── Waxman-Smits ───────────────────────────────────────────────────────────────

def test_waxman_smits_fit(sandbox):
    from physics_sandbox import waxman_smits_conductivity
    sw = np.linspace(0.2, 1.0, 15)
    consts = dict(cw=5.0, b_coeff=0.045, qv=0.3, f_star=12.0)
    ct = waxman_smits_conductivity(sw, 2.0, **consts)
    out = sandbox.fit_waxman_smits(sw, ct, **consts)
    assert out["model"] == "archie_waxman_smits"
    assert out["parameters"]["n_star"] == pytest.approx(2.0, abs=0.1)


def test_waxman_smits_rejects_bad_f_star():
    from physics_sandbox import waxman_smits_conductivity
    with pytest.raises(PhysicalValidationError):
        waxman_smits_conductivity(np.array([0.5]), 2.0, cw=5.0, b_coeff=0.04,
                                  qv=0.3, f_star=0.0)


# ── restricted exec sandbox ────────────────────────────────────────────────────

def test_run_sandboxed_basic_math():
    result = run_sandboxed("result = np.mean(data) * factor",
                           inputs={"data": [1.0, 2.0, 3.0], "factor": 2.0})
    assert result == pytest.approx(4.0)


def test_run_sandboxed_blocks_imports():
    with pytest.raises(SandboxSecurityError):
        run_sandboxed("import os\nresult = 1")


def test_run_sandboxed_blocks_dunder():
    with pytest.raises(SandboxSecurityError):
        run_sandboxed("result = ().__class__.__bases__")


def test_run_sandboxed_blocks_open():
    with pytest.raises(SandboxSecurityError):
        run_sandboxed("result = open('secret.txt').read()")


def test_run_sandboxed_requires_result_assignment():
    with pytest.raises(PhysicalValidationError):
        run_sandboxed("answer = 42")
