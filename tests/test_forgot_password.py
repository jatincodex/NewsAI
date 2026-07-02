import os

os.environ["NEWS_AI_CELERY_TASK_ALWAYS_EAGER"] = "True"
os.environ["NEWS_AI_DATABASE_URL"] = "sqlite:///./test_news_ai_forgot.db"

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import Base, engine

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if os.path.exists("test_news_ai_forgot.db"):
        try:
            os.remove("test_news_ai_forgot.db")
        except:
            pass

def test_forgot_password_flow():
    # 1. Signup a test user
    signup_payload = {
        "username": "resetuser",
        "email": "resetuser@gmail.com",
        "password": "oldpassword123",
        "display_name": "Reset User"
    }
    signup_res = client.post("/auth/signup", json=signup_payload)
    assert signup_res.status_code == 201

    # 2. Trigger forgot password reset code generation
    forgot_payload = {
        "email": "resetuser@gmail.com"
    }
    forgot_res = client.post("/auth/forgot-password", json=forgot_payload)
    assert forgot_res.status_code == 200
    data = forgot_res.json()
    assert "reset_code" in data
    code = data["reset_code"]
    assert len(code) == 6
    assert code.isdigit()
    print("\n[PASS] Forgot password code generated and returned successfully.")

    # 3. Try to request code for a non-existent email
    invalid_forgot = {
        "email": "notfound@gmail.com"
    }
    invalid_forgot_res = client.post("/auth/forgot-password", json=invalid_forgot)
    assert invalid_forgot_res.status_code == 404
    print("[PASS] Non-existent email reset request returned 404.")

    # 4. Attempt password reset with an incorrect code
    invalid_reset = {
        "email": "resetuser@gmail.com",
        "reset_code": "000000",
        "new_password": "newpassword123"
    }
    invalid_reset_res = client.post("/auth/reset-password", json=invalid_reset)
    assert invalid_reset_res.status_code == 400
    print("[PASS] Resetting with invalid code returned 400.")

    # 5. Reset password with correct code
    valid_reset = {
        "email": "resetuser@gmail.com",
        "reset_code": code,
        "new_password": "newpassword123"
    }
    valid_reset_res = client.post("/auth/reset-password", json=valid_reset)
    assert valid_reset_res.status_code == 200
    assert valid_reset_res.json()["message"] == "Password reset successfully."
    print("[PASS] Resetting with correct code succeeded.")

    # 6. Verify logging in with the old password fails
    login_old_res = client.post("/auth/login", json={"username": "resetuser", "password": "oldpassword123"})
    assert login_old_res.status_code == 401
    print("[PASS] Login with old password rejected successfully.")

    # 7. Verify logging in with the new password succeeds
    login_new_res = client.post("/auth/login", json={"username": "resetuser", "password": "newpassword123"})
    assert login_new_res.status_code == 200
    assert "token" in login_new_res.json()
    print("[PASS] Login with new password succeeded.")
