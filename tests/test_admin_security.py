import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)

def test_admin_summary_authentication_required():
    response = client.get("/api/admin/summary")
    assert response.status_code == 401
    assert "detail" in response.json()

def test_admin_analytics_authentication_required():
    response = client.get("/api/admin/analytics")
    assert response.status_code == 401
    assert "detail" in response.json()

def test_admin_feedback_authentication_required():
    response = client.get("/api/admin/feedback")
    assert response.status_code == 401
    assert "detail" in response.json()

def test_admin_users_authentication_required():
    response = client.get("/api/admin/users")
    assert response.status_code == 401
    assert "detail" in response.json()
