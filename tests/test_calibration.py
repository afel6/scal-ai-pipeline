import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Add root to path
sys.path.append(str(Path(__file__).parent.parent))

from app import app

client = TestClient(app)

def test_scal_calibrate_kr():
    payload = {
        "sw": [0.15, 0.3, 0.5, 0.7, 0.8],
        "krw": [0.0, 0.05, 0.15, 0.35, 0.5],
        "kro": [0.8, 0.6, 0.3, 0.05, 0.0],
        "swi": 0.15,
        "sor": 0.2,
        "krw_max": 0.5,
        "kro_max": 0.8,
        "basin_name": "Default"
    }
    
    response = client.post("/api/scal/calibrate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "kr"
    assert "curves" in data
    assert "physics_audit" in data["metadata"]

def test_scal_calibrate_archie():
    payload = {
        "porosity": [0.1, 0.15, 0.2, 0.25, 0.3],
        "formation_factor": [80.0, 40.0, 25.0, 15.0, 10.0],
        "basin_name": "Default"
    }
    
    response = client.post("/api/scal/calibrate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "archie"
    assert "a" in data
    assert "m" in data
    assert len(data["phi_line"]) > 0
    assert len(data["ff_line"]) > 0
    assert "physics_audit" in data
