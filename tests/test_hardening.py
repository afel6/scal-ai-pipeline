# Save as test_hardening.py then: python test_hardening.py
from scal_file_handler import SCALFileHandler, extract_file_data
from physics_validator import PhysicsGuard
import numpy as np

# Test 1 — PhysicsGuard incremental detection
guard = PhysicsGuard()
# Simulate incremental Hg data (each row is a small delta, not cumulative):
pc_fake    = [100, 200, 300, 400, 500, 600, 700]
shg_incr   = [0.01, 0.03, 0.02, 0.04, 0.01, 0.03, 0.02]  # incremental deltas
guard.validate_micp(pc_fake, shg_incr)
result = guard.generate_health_score()
has_incr_rule = any(v['rule'] == 'MICP_INCREMENTAL_COLUMN_DETECTED' for v in result['violations'])
print(f"Test 1 — Incremental detection: {'PASS' if has_incr_rule else 'FAIL'}")

# Test 2 — PhysicsGuard passes clean cumulative data
guard2 = PhysicsGuard()
shg_cumul = [0.05, 0.15, 0.30, 0.50, 0.70, 0.85, 0.94]  # cumulative — monotone increasing
guard2.validate_micp(pc_fake, shg_cumul)
result2 = guard2.generate_health_score()
no_incr_rule = not any(v['rule'] == 'MICP_INCREMENTAL_COLUMN_DETECTED' for v in result2['violations'])
print(f"Test 2 — Cumulative passes clean: {'PASS' if no_incr_rule else 'FAIL'}")

# Test 3 — _pick_micp_sat_col rejects incremental
handler = SCALFileHandler.__new__(SCALFileHandler)
headers = [
    'Pressure (psia)',
    'Incremental Intrusion (%)',    # must be rejected
    'Cumulative Intrusion (%)',     # must be selected
    'Pore Throat Radius (um)',
]
chosen = handler._pick_micp_sat_col(headers)
print(f"Test 3 — Column picker selects cumulative (idx=2): {'PASS' if chosen == 2 else f'FAIL (got {chosen})'}")

print("\nAll tests done.")
