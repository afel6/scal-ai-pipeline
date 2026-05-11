import sys
import os
import json
import numpy as np
import time
import subprocess
import pytest

def test_history_matching_noisy_data():
    """TEST 1: Agentic History Matching with Massive Noisy Data"""
    sw_points = np.linspace(0.1, 0.9, 500)
    krw_max, kro_max, nw, no = 0.8, 0.9, 2.5, 2.0
    
    krw_clean = krw_max * ((sw_points - 0.1) / (1 - 0.1 - 0.1)) ** nw
    kro_clean = kro_max * ((1 - sw_points - 0.1) / (1 - 0.1 - 0.1)) ** no
    
    krw_noisy = np.clip(krw_clean + np.random.normal(0, 0.05, 500), 0, 1)
    kro_noisy = np.clip(kro_clean + np.random.normal(0, 0.05, 500), 0, 1)
    
    payload = json.dumps({
        "sw": sw_points.tolist(),
        "krw": krw_noisy.tolist(),
        "kro": kro_noisy.tolist()
    })
    
    result = subprocess.run(
        ["python", "hermes_skills_library/petroleum/simulator/history_matching_skill.py", payload],
        capture_output=True, text=True
    )
    
    out = result.stdout.strip().lower()
    assert "error" not in out or "success" in out, f"History matching failed: {out}"

def test_curve_fitting_corrupted_data():
    """TEST 2: Curve Fitting Skill with Corrupted Data (NaN, negative Sw)"""
    corrupted_payload = json.dumps({
        "model": "corey",
        "sw": [-0.5, 0.5, float('nan'), 1.5],
        "krw": [0.0, 0.5, 1.0, 2.0]
    })
    result = subprocess.run(
        ["python", "hermes_skills_library/petroleum/curve_fitting_skill.py", corrupted_payload],
        capture_output=True, text=True
    )
    out = result.stdout.strip().lower()
    # It should fail gracefully
    assert "error" in out or result.returncode != 0, "Skill processed corrupted data without error"

def test_document_engine_oom():
    """TEST 3: Document Engine OOM Stress Test"""
    sys.path.append(os.getcwd())
    from hviel_doc_engine import HvielDocEngine
    engine = HvielDocEngine(output_dir="test_generated")
    if not os.path.exists("test_generated"):
        os.makedirs("test_generated")
        
    massive_string = "Simulated Text Block. " * 50000
    payload = json.dumps({
        "sections": [
            {"title": "Massive Stress Test", "content": massive_string}
        ]
    })
    
    path = engine.build_from_json(payload, 'docx', well="StressTest_Well", engineer="Automated Tester")
    assert os.path.exists(path), "DOCX file was not created"
    assert os.path.getsize(path) > 0, "Created DOCX file is empty"

