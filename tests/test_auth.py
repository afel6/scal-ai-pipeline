import pytest
from fastapi.testclient import TestClient
from app import app
import app as main_app

# Mock ADMIN_PIN
main_app.ADMIN_PIN = "super-secret"

client = TestClient(main_app.app)

def test_user_login_success():
    response = client.post("/api/auth", data={"pin": "super-secret"})
    assert response.status_code == 200
    assert response.json() == {"status": "success"}

def test_user_login_failure():
    response = client.post("/api/auth", data={"pin": "wrong-secret"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid Access Code"}

def test_admin_login_success():
    response = client.post("/api/admin/auth", data={"pin": "super-secret"})
    assert response.status_code == 200
    assert "token" in response.json()

def test_admin_login_failure():
    response = client.post("/api/admin/auth", data={"pin": "wrong-secret"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid Admin PIN"}

def test_admin_login_empty_target_pin():
    # If ADMIN_PIN is not set, login should fail for any PIN (even empty string)
    original_pin = main_app.ADMIN_PIN
    try:
        main_app.ADMIN_PIN = ""
        response = client.post("/api/admin/auth", data={"pin": "something"})
        assert response.status_code == 401
    finally:
        main_app.ADMIN_PIN = original_pin
