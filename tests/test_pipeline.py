import os
import time

# Configure environment before importing any app components
os.environ["NEWS_AI_CELERY_TASK_ALWAYS_EAGER"] = "True"
os.environ["NEWS_AI_DATABASE_URL"] = "sqlite:///./test_news_ai.db"

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import Base, engine, SessionLocal
from app.models.models import SocialPost, TrustedDocument

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    # Create test database tables
    Base.metadata.create_all(bind=engine)
    # Clear database before test
    db = SessionLocal()
    db.query(SocialPost).delete()
    db.query(TrustedDocument).delete()
    db.commit()
    db.close()
    yield
    # Clean up test database tables
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if os.path.exists("test_news_ai.db"):
        os.remove("test_news_ai.db")

def test_verification_and_routing_pipeline():
    # 1. Populate system with trusted news documents
    doc1_payload = {
        "title": "NASA Solar Storm Alert",
        "content": "A massive solar flare is heading towards Earth, expected to cause a global internet blackout tomorrow."
    }
    doc2_payload = {
        "title": "SpaceX Starship Launch",
        "content": "SpaceX successfully launched its Starship rocket for its fifth flight test from Starbase, Texas, demonstrating a soft water landing of the booster."
    }
    
    response = client.post("/trusted-docs", json=doc1_payload)
    assert response.status_code == 201
    doc1 = response.json()
    assert doc1["title"] == "NASA Solar Storm Alert"
    
    response = client.post("/trusted-docs", json=doc2_payload)
    assert response.status_code == 201
    
    # Verify the document list
    response = client.get("/trusted-docs")
    assert response.status_code == 200
    assert len(response.json()) == 2

    # 2. Case A: Ingest a matching story (Confidence Score >= 0.95)
    # The text contains the exact sentence from the trusted document.
    matching_post = {
        "source": "X",
        "post_id": "x_post_1001",
        "username": "science_tracker",
        "content": "A massive solar flare is heading towards Earth, expected to cause a global internet blackout tomorrow.",
        "timestamp": "2026-06-18T12:00:00Z",
        "metadata": {
            "likes": 15000,
            "retweets": 4500
        }
    }
    
    response = client.post("/ingest", json=matching_post)
    assert response.status_code == 201
    post_a_initial = response.json()
    assert post_a_initial["post_id"] == "x_post_1001"
    
    # Since CELERY_TASK_ALWAYS_EAGER is True, the task runs synchronously inside the request.
    # We can fetch post details immediately to check the completed verification state.
    response = client.get(f"/posts/{post_a_initial['post_id']}")
    assert response.status_code == 200
    post_a_processed = response.json()
    
    assert post_a_processed["confidence_score"] >= 0.95
    assert post_a_processed["status"] in ("video_generation_pending", "published")
    assert post_a_processed["matched_document_id"] == doc1["id"]
    print(f"\n[PASS] Match Test: Score = {post_a_processed['confidence_score']}, Status = {post_a_processed['status']}")

    # 3. Case B: Ingest an unverified story (Confidence Score < 0.95)
    # This text contains a fake rumor not found in the trusted documents.
    unverified_post = {
        "source": "Instagram",
        "post_id": "insta_post_2002",
        "username": "rumor_mill",
        "content": "Rumors say that scientists found aliens living in the subways of London yesterday evening.",
        "timestamp": "2026-06-18T12:05:00Z",
        "metadata": {
            "likes": 300,
            "retweets": 0
        }
    }
    
    response = client.post("/ingest", json=unverified_post)
    assert response.status_code == 201
    post_b_initial = response.json()
    
    response = client.get(f"/posts/{post_b_initial['post_id']}")
    assert response.status_code == 200
    post_b_processed = response.json()
    
    assert post_b_processed["confidence_score"] < 0.95
    assert post_b_processed["status"] == "human_review_required"
    assert post_b_processed["matched_document_id"] is None or post_b_processed["confidence_score"] < 0.95
    print(f"[PASS] Unverified Test: Score = {post_b_processed['confidence_score']}, Status = {post_b_processed['status']}")

    # 4. Verify the lists endpoint reflects correct status divisions
    response = client.get("/posts?status_filter=published")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["post_id"] == "x_post_1001"
    
    response = client.get("/posts?status_filter=human_review_required")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["post_id"] == "insta_post_2002"
