import pytest
import json
import numpy as np
from hermes_skills_library.petroleum.scalskills.scripts.petrophysics import PetrophysicsSkills

def test_klinkenberg_single_point():
    # ka = 100 mD, pm = 14.7 psi (1 atm)
    # empirical equation: b = 0.777 * KL**-0.39
    # solving: KL * (1 + b/14.7) = 100
    res = PetrophysicsSkills.calculate_klinkenberg([100.0], pm=14.7)
    assert res["status"] == "success"
    assert len(res["samples"]) == 1
    sample = res["samples"][0]
    kl = sample["kl_md"]
    b = sample["b_slippage"]
    # Check physical convergence: KL must be less than Ka due to gas slippage
    assert kl < 100.0
    assert abs(kl * (1.0 + b / 14.7) - 100.0) < 1e-3

def test_klinkenberg_zero_pressure():
    res = PetrophysicsSkills.calculate_klinkenberg([50.0], pm=0.0)
    assert res["status"] == "success"
    assert res["samples"][0]["kl_md"] == 0.0

def test_retort_saturation():
    # raw water = 1.5 cc, raw oil = 2.0 cc, pore volume = 4.0 cc
    # water corr: 0.85 * 1.5 = 1.275 cc
    # oil corr: 1.01 * 2.0 = 2.02 cc
    # Sw = 1.275 / 4.0 = 31.875%
    # So = 2.02 / 4.0 = 50.5%
    # Sg = 100 - 31.875 - 50.5 = 17.625%
    res = PetrophysicsSkills.calculate_retort_saturation([1.5], [2.0], [4.0])
    assert res["status"] == "success"
    sample = res["samples"][0]
    assert sample["vw_corr_cc"] == 1.275
    assert sample["vo_corr_cc"] == 2.02
    assert abs(sample["sw_pct"] - 31.88) < 0.1
    assert abs(sample["so_pct"] - 50.5) < 0.1
    assert abs(sample["sg_pct"] - 17.63) < 0.1

def test_dean_stark_saturation():
    # extracted water = 1.2 cc, pre weight = 120g, post weight = 115g, pv = 3.5 cc
    # loss = 5.0 g. oil wt = 5.0 - 1.2 * 1.0 = 3.8 g
    # oil vol = 3.8 / 0.8 = 4.75 cc (with rho_o = 0.8)
    # Sw = 1.2 / 3.5 = 34.29%
    # So = 4.75 / 3.5 = 135.7% (physically exceeds, but mathematically verified)
    res = PetrophysicsSkills.calculate_dean_stark([1.2], [120.0], [115.0], [3.5], rho_o=0.8)
    assert res["status"] == "success"
    sample = res["samples"][0]
    assert sample["w_loss_g"] == 5.0
    assert sample["vo_calc_cc"] == 4.75
    assert abs(sample["sw_pct"] - 34.29) < 0.1

def test_boyles_law_porosity():
    # P1 = 100 psi, P2 = 45 psi, V1 = 100 cc, V_added = 80 cc, V_bulk = 50 cc
    # Vg = 100 + 80 - 100 * (100 / 45) = 180 - 222.22 = -42.22 cc (clipped to 0)
    # let's use positive volume parameters:
    # P1 = 50 psi, P2 = 25 psi, V1 = 100 cc, V_added = 80 cc, V_bulk = 100 cc
    # Vg = 100 + 80 - 100 * (50 / 25) = 180 - 200 = -20 (clipped to 0)
    # let's use proper realistic pressures:
    # P1 = 100 psi, P2 = 75 psi, V1 = 100 cc, V_added = 50 cc, V_bulk = 40 cc
    # Vg = 100 + 50 - 100 * (100 / 75) = 150 - 133.33 = 16.67 cc
    # Vp = 40 - 16.67 = 23.33 cc
    # phi = 23.33 / 40 = 58.33%
    res = PetrophysicsSkills.calculate_boyles_law_porosity([100.0], [75.0], 100.0, 50.0, [40.0])
    assert res["status"] == "success"
    sample = res["samples"][0]
    assert abs(sample["vg_cc"] - 16.67) < 0.05
    assert abs(sample["vp_cc"] - 23.33) < 0.05
    assert abs(sample["phi_pct"] - 58.33) < 0.1

def test_amott_wettability():
    # spontaneous water = 2.0 cc, forced water = 1.0 cc
    # spontaneous oil = 0.5 cc, forced oil = 3.5 cc
    # Iw = 2 / 3 = 0.667
    # Io = 0.5 / 4 = 0.125
    # IAH = 0.667 - 0.125 = 0.542 -> Strongly Water-Wet
    res = PetrophysicsSkills.calculate_amott_wettability([2.0], [1.0], [0.5], [3.5])
    assert res["status"] == "success"
    sample = res["samples"][0]
    assert abs(sample["iw"] - 0.6667) < 1e-3
    assert abs(sample["io"] - 0.125) < 1e-3
    assert abs(sample["iah"] - 0.5417) < 1e-3
    assert sample["wettability_state"] == "Water-Wet"

def test_xrd_mineralogy_audit():
    # valid sum
    minerals_ok = {
        "quartz": [60.0],
        "feldspar": [20.0],
        "calcite": [15.0],
        "smectite": [5.0]
    }
    res = PetrophysicsSkills.audit_xrd_mineralogy(minerals_ok)
    assert res["status"] == "success"
    sample = res["samples"][0]
    assert sample["total_sum"] == 100.0
    assert sample["sum_violation"] is False
    assert sample["smectite_warning"] is True  # smectite > 2.0%

    # invalid sum
    minerals_bad = {
        "quartz": [50.0],
        "feldspar": [20.0],
        "calcite": [15.0],
        "smectite": [0.5]
    }
    res2 = PetrophysicsSkills.audit_xrd_mineralogy(minerals_bad)
    sample2 = res2["samples"][0]
    assert sample2["total_sum"] == 85.5
    assert sample2["sum_violation"] is True
    assert sample2["smectite_warning"] is False

def test_nmr_t2_partitioning():
    t2_times = [1.0, 2.0, 10.0, 33.0, 50.0, 100.0]
    # sandstone default cutoff is 33 ms
    # amplitudes <= 33 ms: 0.1 + 0.2 + 0.3 + 0.4 = 1.0 (BVI)
    # amplitudes > 33 ms: 0.5 + 0.5 = 1.0 (FFI)
    # total nmr porosity = 2.0, free ratio = 50.0%
    amplitudes = [0.1, 0.2, 0.3, 0.4, 0.5, 0.5]
    res = PetrophysicsSkills.calculate_nmr_t2_distribution(t2_times, amplitudes, cutoff_ms=33.0)
    assert res["status"] == "success"
    sample = res["samples"][0]
    assert sample["bvi_bound"] == 1.0
    assert sample["ffi_free"] == 1.0
    assert sample["total_nmr_porosity"] == 2.0
    assert sample["free_fluid_ratio"] == 0.5

def test_ct_scan_interpretation():
    # hu = 1450 (Sandstone), hu = 90 (fracture)
    res = PetrophysicsSkills.interpret_ct_scan([1450.0, 90.0])
    assert res["status"] == "success"
    samples = res["samples"]
    assert samples[0]["lithology"] == "Sandstone"
    assert samples[0]["fractured_identified"] is False
    assert samples[1]["lithology"] == "Mixed/Unknown"  # 90 is outside standard bulk lithology ranges
    assert samples[1]["fractured_identified"] is True

def test_supplementary_properties():
    # SG = 0.85 -> API = 141.5 / 0.85 - 131.5 = 34.97
    # w_init = 10.0g, w_acid = 1.0g -> Solubility = 90% -> Carbonate True
    res = PetrophysicsSkills.calculate_supplementary_properties(sg=[0.85], w_init=[10.0], w_acid=[1.0])
    assert res["status"] == "success"
    sample = res["samples"][0]
    assert abs(sample["api_gravity"] - 34.97) < 0.05
    assert sample["solubility_pct"] == 90.0
    assert sample["carbonate_rock"] is True

def test_rqi_fzi_robust_sorting():
    # phi = 10% (0.10) for all. perm = 100 mD (high), 10 mD (medium), 0.1 mD (low)
    phi = [0.10, 0.10, 0.10]
    perm = [100.0, 10.0, 0.1]
    res = PetrophysicsSkills.calculate_rqi_fzi(phi, perm, k=3)
    assert res["status"] == "success"
    samples = res["samples"]
    # Verify highest perm (100 mD) gets HU 1 (Excellent)
    assert samples[0]["hu"] == 1
    assert "Excellent" in samples[0]["hu_quality"]
    # Verify lowest perm (0.1 mD) gets HU 3 (Poor/Tight)
    assert samples[2]["hu"] == 3
    assert "Poor/Tight" in samples[2]["hu_quality"]
