# Save as test_hardening.py then: pytest tests/test_hardening.py
from scal_file_handler import SCALFileHandler, extract_file_data
from physics_validator import PhysicsGuard
from extractors.micp import MICPExtractor
import numpy as np

def test_physics_guard_incremental_detection():
    # Test 1 — PhysicsGuard incremental detection
    guard = PhysicsGuard()
    # Simulate incremental Hg data (each row is a small delta, not cumulative):
    pc_fake    = [100, 200, 300, 400, 500, 600, 700]
    shg_incr   = [0.01, 0.03, 0.02, 0.04, 0.01, 0.03, 0.02]  # incremental deltas
    guard.validate_micp(pc_fake, shg_incr)
    result = guard.generate_health_score()
    has_incr_rule = any(v['rule'] == 'MICP_INCREMENTAL_COLUMN_DETECTED' for v in result['violations'])
    assert has_incr_rule, "Should detect incremental columns"

def test_physics_guard_passes_clean_cumulative_data():
    # Test 2 — PhysicsGuard passes clean cumulative data
    guard2 = PhysicsGuard()
    pc_fake    = [100, 200, 300, 400, 500, 600, 700]
    shg_cumul = [0.05, 0.15, 0.30, 0.50, 0.70, 0.85, 0.94]  # cumulative — monotone increasing
    guard2.validate_micp(pc_fake, shg_cumul)
    result2 = guard2.generate_health_score()
    no_incr_rule = not any(v['rule'] == 'MICP_INCREMENTAL_COLUMN_DETECTED' for v in result2['violations'])
    assert no_incr_rule, "Cumulative data should pass cleanly"

def test_pick_micp_sat_col_rejects_incremental():
    # Test 3 — _pick_micp_sat_col rejects incremental
    handler = MICPExtractor.__new__(MICPExtractor)
    headers = [
        'Pressure (psia)',
        'Incremental Intrusion (%)',    # must be rejected
        'Cumulative Intrusion (%)',     # must be selected
        'Pore Throat Radius (um)',
    ]
    chosen = handler._pick_micp_sat_col(headers)
    assert chosen == 2, f"Should choose cumulative (idx=2), but got {chosen}"
