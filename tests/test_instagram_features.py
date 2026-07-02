import os
import shutil
from pathlib import Path

# Configure environment variables for test execution
os.environ["NEWS_AI_CELERY_TASK_ALWAYS_EAGER"] = "True"
os.environ["NEWS_AI_DATABASE_URL"] = "sqlite:///./test_instagram_news.db"

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import Base, engine, SessionLocal
from app.models.models import SocialPost, TrustedDocument, User, Follow, Comment, SavedPost, DirectMessage
from app.core.config import settings

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    # Make sure folders are created and clean
    for path in [settings.TRUSTED_DOCS_DIR, settings.GENERATED_VIDEOS_DIR, settings.GENERATED_IMAGES_DIR]:
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.query(SocialPost).delete()
    db.query(TrustedDocument).delete()
    db.query(User).delete()
    db.query(Follow).delete()
    db.query(Comment).delete()
    db.query(SavedPost).delete()
    db.query(DirectMessage).delete()
    db.commit()
    db.close()
    yield
    # Cleanup after test
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if os.path.exists("test_instagram_news.db"):
        os.remove("test_instagram_news.db")
        
    for path in [settings.TRUSTED_DOCS_DIR, settings.GENERATED_VIDEOS_DIR, settings.GENERATED_IMAGES_DIR]:
        if path.exists():
            shutil.rmtree(path)

def test_complete_instagram_news_features():
    # 0. Assert non-Gmail signups are rejected
    bad_payload = {
        "username": "baduser",
        "email": "baduser@yahoo.com",
        "password": "somepassword",
        "display_name": "Bad User"
    }
    response = client.post("/auth/signup", json=bad_payload)
    assert response.status_code == 400
    assert "Gmail" in response.json()["detail"]
    print("\n[PASS] Non-Gmail signups successfully blocked.")

    # 1. Sign up Alice (with valid Gmail)
    alice_payload = {
        "username": "alice",
        "email": "alice@gmail.com",
        "password": "alicepassword123",
        "display_name": "Alice Reporter"
    }
    response = client.post("/auth/signup", json=alice_payload)
    assert response.status_code == 201
    alice_data = response.json()
    alice_token = alice_data["token"]
    assert alice_data["user"]["username"] == "alice"
    assert alice_data["user"]["display_name"] == "Alice Reporter"
    
    # 2. Sign up Bob (with valid Gmail)
    bob_payload = {
        "username": "bob",
        "email": "bob@gmail.com",
        "password": "bobpassword123",
        "display_name": "Bob Editor"
    }
    response = client.post("/auth/signup", json=bob_payload)
    assert response.status_code == 201
    bob_data = response.json()
    bob_token = bob_data["token"]
    
    # 2b. Test Continue with Google OAuth endpoint
    # Negative test: Non-Gmail account
    google_bad = {
        "email": "charlie@yahoo.com",
        "display_name": "Charlie"
    }
    response = client.post("/auth/google", json=google_bad)
    assert response.status_code == 400
    
    # Positive test: Register new Google user
    google_good = {
        "email": "charlie@gmail.com",
        "display_name": "Charlie Google"
    }
    response = client.post("/auth/google", json=google_good)
    assert response.status_code == 200
    charlie_data = response.json()
    assert charlie_data["user"]["email"] == "charlie@gmail.com"
    assert charlie_data["user"]["display_name"] == "Charlie Google"
    assert charlie_data["user"]["username"] == "charlie"
    print("[PASS] Continue with Google registers new user successfully.")

    # Positive test: Log in existing Google user
    response = client.post("/auth/google", json=google_good)
    assert response.status_code == 200
    charlie_login_data = response.json()
    assert charlie_login_data["user"]["id"] == charlie_data["user"]["id"]
    print("[PASS] Continue with Google logs in existing user successfully.")
    
    # 3. Test Profile Stats and Follow System
    # Alice follows Bob
    headers_alice = {"Authorization": f"Bearer {alice_token}"}
    headers_bob = {"Authorization": f"Bearer {bob_token}"}
    
    response = client.post("/users/bob/follow", headers=headers_alice)
    assert response.status_code == 200
    assert response.json()["status"] == "followed"
    print("\n[PASS] Alice successfully followed Bob.")
    
    # Get Bob's profile to verify follower count
    response = client.get("/users/bob/profile", headers=headers_alice)
    assert response.status_code == 200
    bob_profile = response.json()
    assert bob_profile["followers_count"] == 1
    assert bob_profile["is_following"] is True
    print(f"[PASS] Bob's profile metrics verified. Followers: {bob_profile['followers_count']}")
    
    # 4. Test Direct Messaging (DMs)
    # Alice sends a DM to Bob
    dm_payload = {
        "recipient_username": "bob",
        "text": "Hi Bob, check out the breaking solar flare news story!"
    }
    response = client.post("/messages", json=dm_payload, headers=headers_alice)
    assert response.status_code == 200
    assert response.json()["text"] == "Hi Bob, check out the breaking solar flare news story!"
    
    # Bob reads messages from Alice
    response = client.get("/messages?with_user=alice", headers=headers_bob)
    assert response.status_code == 200
    msgs = response.json()
    assert len(msgs) == 1
    assert msgs[0]["sender_username"] == "alice"
    assert msgs[0]["text"] == "Hi Bob, check out the breaking solar flare news story!"
    print("[PASS] Direct messaging between Alice and Bob verified successfully.")
    
    # 5. Seed reference fact document
    doc_payload = {
        "title": "NASA Solar Storm Alert",
        "content": "A massive solar flare is heading towards Earth, expected to cause a global internet blackout tomorrow."
    }
    response = client.post("/trusted-docs", json=doc_payload)
    assert response.status_code == 201
    
    # 6. Ingest post (verified -> generates image & video)
    post_payload = {
        "source": "NewsAI",
        "post_id": "verified_post_100",
        "username": "alice",
        "content": "A massive solar flare is heading towards Earth, expected to cause a global internet blackout tomorrow.",
        "timestamp": "2026-06-27T08:00:00Z"
    }
    response = client.post("/ingest", json=post_payload, headers=headers_alice)
    assert response.status_code == 201
    
    # Wait for Celery eager execution to complete and inspect post
    response = client.get("/posts/verified_post_100")
    assert response.status_code == 200
    post_data = response.json()
    assert post_data["status"] == "published"
    assert post_data["video_path"] is not None
    assert post_data["image_path"] is not None
    assert os.path.exists(post_data["video_path"])
    assert os.path.exists(post_data["image_path"])
    print("[PASS] News verification successfully generated static image card and vertical reel.")
    
    # 7. Alice likes the post
    response = client.post("/posts/verified_post_100/like?action=like", headers=headers_alice)
    assert response.status_code == 200
    assert response.json()["likes_count"] == 1
    print("[PASS] Post likes counter incremented successfully.")
    
    # 8. Bob comments on the post
    comment_payload = {
        "text": "Wow, this is an incredible fact-checked news card!"
    }
    response = client.post("/posts/verified_post_100/comments", json=comment_payload, headers=headers_bob)
    assert response.status_code == 200
    assert response.json()["text"] == "Wow, this is an incredible fact-checked news card!"
    assert response.json()["username"] == "bob"
    
    # Get post comments thread
    response = client.get("/posts/verified_post_100/comments")
    assert response.status_code == 200
    comments = response.json()
    assert len(comments) == 1
    assert comments[0]["username"] == "bob"
    assert comments[0]["text"] == "Wow, this is an incredible fact-checked news card!"
    print("[PASS] Post comments thread registered and retrieved successfully.")
    
    # 9. Bob saves/bookmarks the post
    response = client.post("/posts/verified_post_100/save", headers=headers_bob)
    assert response.status_code == 200
    
    # Get Bob's saved posts list
    response = client.get("/posts/saved", headers=headers_bob)
    assert response.status_code == 200
    saved_posts = response.json()
    assert len(saved_posts) == 1
    assert saved_posts[0]["post_id"] == "verified_post_100"
    print("[PASS] Post bookmarking / saved tab functionality verified successfully.")

    # 10. Test Custom Post with Image file Upload
    import io
    dummy_image = io.BytesIO(b"dummy image data")
    response = client.post(
        "/posts/create",
        data={"content": "This is a custom post with an attached image!"},
        files={"file": ("test_upload.png", dummy_image, "image/png")},
        headers=headers_alice
    )
    assert response.status_code == 201
    post_res = response.json()
    assert post_res["content"] == "This is a custom post with an attached image!"
    assert post_res["image_path"] is not None
    assert post_res["video_path"] is None
    assert os.path.exists(post_res["image_path"])
    print("[PASS] Custom post with file upload created successfully.")
