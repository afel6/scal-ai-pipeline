import sys
import os
import json
import numpy as np
import time
import subprocess

print("--- STARTING PRC PIPELINE STRESS TEST ---")

# 1. Generate Fake Noisy SCAL Data for History Matching (500 points)
print("\n[*] TEST 1: Agentic History Matching with Massive Noisy Data...")
try:
    sw_points = np.linspace(0.1, 0.9, 500)
    krw_max, kro_max, nw, no = 0.8, 0.9, 2.5, 2.0
    
    krw_clean = krw_max * ((sw_points - 0.1) / (1 - 0.1 - 0.1)) ** nw
    kro_clean = kro_max * ((1 - sw_points - 0.1) / (1 - 0.1 - 0.1)) ** no
    
    # Add significant Gaussian noise
    krw_noisy = krw_clean + np.random.normal(0, 0.05, 500)
    kro_noisy = kro_clean + np.random.normal(0, 0.05, 500)
    
    # Ensure physical boundaries
    krw_noisy = np.clip(krw_noisy, 0, 1)
    kro_noisy = np.clip(kro_noisy, 0, 1)
    
    payload = json.dumps({
        "sw": sw_points.tolist(),
        "krw": krw_noisy.tolist(),
        "kro": kro_noisy.tolist()
    })
    
    start_time = time.time()
    result = subprocess.run(
        ["python", "hermes_skills_library/petroleum/simulator/history_matching_skill.py", payload],
        capture_output=True, text=True
    )
    duration = time.time() - start_time
    
    out = result.stdout.strip()
    if "error" in out.lower() and "success" not in out.lower():
        print(f"  [X] FAILED! Error output: {out}")
    else:
        print(f"  [PASS] PASSED! (Duration: {duration:.2f}s)")
        print(f"      Output preview: {out[:150]}...")
except Exception as e:
    print(f"  [X] EXCEPTION: {e}")

# 2. Corrupted Data Test for Curve Fitting
print("\n[*] TEST 2: Curve Fitting Skill with Corrupted Data (NaN, negative Sw)...")
try:
    corrupted_payload = json.dumps({
        "model": "corey",
        "sw": [-0.5, 0.5, float('nan'), 1.5],
        "krw": [0.0, 0.5, 1.0, 2.0]
    })
    result = subprocess.run(
        ["python", "hermes_skills_library/petroleum/curve_fitting_skill.py", corrupted_payload],
        capture_output=True, text=True
    )
    out = result.stdout.strip()
    if "error" in out.lower() or result.returncode != 0:
        print(f"  [PASS] GRACEFUL FAIL! Skill caught the error instead of crashing: {out[:100]}")
    else:
        print(f"  [!] WARNING: Skill processed corrupted data without error. Output: {out[:100]}")
except Exception as e:
    print(f"  [X] EXCEPTION: {e}")

# 3. Document Engine OOM Test
print("\n[*] TEST 3: Document Engine OOM Stress Test (Massive String)...")
try:
    sys.path.append(os.getcwd())
    from hviel_doc_engine import HvielDocEngine
    engine = HvielDocEngine(output_dir="test_generated")
    if not os.path.exists("test_generated"):
        os.makedirs("test_generated")
        
    massive_string = "Simulated Text Block. " * 50000  # ~1 million characters
    payload = json.dumps({
        "sections": [
            {"title": "Massive Stress Test", "content": massive_string}
        ]
    })
    start_time = time.time()
    path = engine.build_from_json(payload, 'docx', well="StressTest_Well", engineer="Automated Tester")
    duration = time.time() - start_time
    print(f"  [PASS] PASSED! Generated massive DOCX at {path} in {duration:.2f}s without OOM crash.")
except Exception as e:
    print(f"  [X] FAILED! OOM or Crash detected: {e}")

print("\n--- STRESS TEST COMPLETE ---")
