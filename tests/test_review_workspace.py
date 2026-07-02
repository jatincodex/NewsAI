import os
import shutil
from pathlib import Path

# Configure environment before importing any app components
os.environ["NEWS_AI_CELERY_TASK_ALWAYS_EAGER"] = "True"
os.environ["NEWS_AI_DATABASE_URL"] = "sqlite:///./test_news_ai_review.db"

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import Base, engine, SessionLocal
from app.models.models import SocialPost, TrustedDocument
from app.core.config import settings

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    # Make sure generated videos directory is empty
    if settings.GENERATED_VIDEOS_DIR.exists():
        shutil.rmtree(settings.GENERATED_VIDEOS_DIR)
    settings.GENERATED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    # Create test database tables
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.query(SocialPost).delete()
    db.query(TrustedDocument).delete()
    db.commit()
    db.close()
    yield
    # Clean up test database tables and files
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    
    if os.path.exists("test_news_ai_review.db"):
        os.remove("test_news_ai_review.db")
        
    # Clear generated test videos
    if settings.GENERATED_VIDEOS_DIR.exists():
        shutil.rmtree(settings.GENERATED_VIDEOS_DIR)

def test_manual_review_approval_and_rejection():
    # 1. Populate reference data
    doc_payload = {
        "title": "NASA Moon Mission",
        "content": "NASA Artemis astronauts will land on the lunar south pole next year to conduct geological surveys."
    }
    response = client.post("/trusted-docs", json=doc_payload)
    assert response.status_code == 201
    
    # 2. Ingest unverified post (expected score < 0.95 -> status 'human_review_required')
    unverified_post = {
        "source": "X",
        "post_id": "review_post_777",
        "username": "space_rumors",
        "content": "Rumors say that astronauts are refusing to fly on the next NASA Artemis mission.",
        "timestamp": "2026-06-27T08:00:00Z"
    }
    
    response = client.post("/ingest", json=unverified_post)
    assert response.status_code == 201
    
    # Fetch post details and check status
    response = client.get("/posts/review_post_777")
    assert response.status_code == 200
    post_data = response.json()
    assert post_data["confidence_score"] < 0.95
    assert post_data["status"] == "human_review_required"
    assert post_data["video_path"] is None
    print(f"\n[PASS] Unverified post initially routed to human_review_required. Score: {post_data['confidence_score']}")
    
    # 3. Call Approve Override Endpoint
    response = client.post("/posts/review_post_777/approve")
    assert response.status_code == 200
    approved_post_data = response.json()
    
    # In eager mode, approval should trigger video generation immediately.
    # Therefore, status should transition to 'published' and video file should exist.
    assert approved_post_data["status"] == "published"
    assert approved_post_data["video_path"] is not None
    assert os.path.exists(approved_post_data["video_path"])
    print(f"[PASS] Manual Approve Override processed successfully. Status: {approved_post_data['status']}, Video generated.")

    # 4. Ingest another unverified post to test Reject Endpoint
    unverified_post_2 = {
        "source": "Instagram",
        "post_id": "review_post_888",
        "username": "gossip_agent",
        "content": "Fake leak shows NASA Artemis is completely canceled.",
        "timestamp": "2026-06-27T08:05:00Z"
    }
    response = client.post("/ingest", json=unverified_post_2)
    assert response.status_code == 201
    
    # Call Reject Endpoint
    response = client.post("/posts/review_post_888/reject")
    assert response.status_code == 200
    rejected_post_data = response.json()
    
    # Post should transition to 'rejected' status and contain no video file.
    assert rejected_post_data["status"] == "rejected"
    assert rejected_post_data["video_path"] is None
    print(f"[PASS] Manual Rejection processed successfully. Status: {rejected_post_data['status']}")
