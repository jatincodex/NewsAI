import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.firebase_config import get_db_client, verify_token

client = TestClient(app)

def test_firebase_config_mock_operations():
    db = get_db_client()
    
    # Test setting a document
    doc_ref = db.collection("users").document("test_uid_123")
    doc_ref.set({
        "id": "test_uid_123",
        "username": "firetest",
        "email": "firetest@gmail.com"
    })
    
    # Test fetching the document
    snap = doc_ref.get()
    assert snap.exists is True
    data = snap.to_dict()
    assert data["username"] == "firetest"
    assert data["email"] == "firetest@gmail.com"

    # Test querying the collection
    results = db.collection("users").where("email", "==", "firetest@gmail.com").get()
    assert len(results) == 1
    assert results[0].to_dict()["username"] == "firetest"

    # Test updating a document
    doc_ref.update({"display_name": "Firebase User"})
    assert doc_ref.get().to_dict()["display_name"] == "Firebase User"

    # Test deleting a document
    doc_ref.delete()
    assert doc_ref.get().exists is False

def test_firebase_token_mock_verification():
    payload = {
        "uid": "uid_alice",
        "email": "alice@gmail.com",
        "name": "Alice"
    }
    import json
    token = json.dumps(payload)
    
    decoded = verify_token(token)
    assert decoded["uid"] == "uid_alice"
    assert decoded["email"] == "alice@gmail.com"
    assert decoded["name"] == "Alice"

def test_auth_me_firebase_integration():
    # Attempt to access protected endpoint without token
    res = client.get("/auth/me")
    assert res.status_code == 401
    
    # Access with valid token
    payload = {
        "uid": "uid_bob",
        "email": "bob@gmail.com",
        "name": "Bob Builder"
    }
    import json
    token = json.dumps(payload)
    
    headers = {"Authorization": f"Bearer {token}"}
    res = client.get("/auth/me", headers=headers)
    assert res.status_code == 200
    
    user_data = res.json()
    assert user_data["id"] == "uid_bob"
    assert user_data["email"] == "bob@gmail.com"
