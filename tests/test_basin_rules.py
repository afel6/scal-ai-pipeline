import sys
from pathlib import Path

# Add root to path just in case
sys.path.append(str(Path(__file__).parent.parent))

from app import db, init_db
from physics_validator import PhysicsGuard

def test_basin_physics_rules():
    # Make sure DB is initialized
    init_db()

    # Clear old test values if any
    db("DELETE FROM basin_physics_rules WHERE basin_name = 'TestBasin'")

    # Insert test rules
    db("INSERT INTO basin_physics_rules (basin_name, rule_key, min_limit, max_limit) VALUES "
       "('TestBasin', 'm', 1.0, 3.0), "
       "('TestBasin', 'a', 0.8, 1.2) "
       "ON CONFLICT (basin_name, rule_key) DO NOTHING")

    # 1. Test PhysicsGuard with Default basin
    guard_default = PhysicsGuard()
    # default m range is [1.3, 2.5]
    # m = 1.1 should fail
    guard_default.validate_archie_parameters(a=1.0, m=1.1, b=1.0, n=2.0, basin_name="Default")
    assert len(guard_default._violations) > 0
    assert any("Cementation exponent m = 1.1" in v["detail"] for v in guard_default._violations)

    # 2. Test PhysicsGuard with TestBasin
    guard_custom = PhysicsGuard()
    # TestBasin m range is [1.0, 3.0]
    # m = 1.1 should pass!
    guard_custom.validate_archie_parameters(a=1.0, m=1.1, b=1.0, n=2.0, basin_name="TestBasin")
    assert len(guard_custom._violations) == 0

    # Clean up
    db("DELETE FROM basin_physics_rules WHERE basin_name = 'TestBasin'")
