from fastapi.testclient import TestClient

# Mock ADMIN_PIN to bypass the empty string issue if env wasn't set.
# The route logic uses `hmac.compare_digest(input_pin, ADMIN_PIN)`.
import app as main_app
main_app.ADMIN_PIN = "super-secret"

client = TestClient(main_app.app)

def test_telemetry_metrics_auth():
    # Test unauthorized
    response = client.get("/api/v1/telemetry/metrics")
    assert response.status_code == 401

    # Test authorized
    response = client.get("/api/v1/telemetry/metrics", headers={"x-admin-pin": "super-secret"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "metrics" in data
    # Check if either postgres or sqlite metrics are returned
    metrics = data["metrics"]
    has_pg = "pg_pool_active_connections" in metrics
    has_sqlite = "sqlite_db_size_kb" in metrics
    assert has_pg or has_sqlite

    # Verify enhanced metrics
    assert "db_pool_health" in metrics
    assert metrics["db_pool_health"] in ["healthy", "exhausted", "uninitialized", "error"]
    
    if has_pg:
        assert "pg_wal_size_kb" in metrics
    if has_sqlite:
        assert "sqlite_wal_size_kb" in metrics
