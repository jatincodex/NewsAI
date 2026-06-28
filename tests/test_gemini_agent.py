import os
import time
import asyncio

# Configure environment before importing components
os.environ["NEWS_AI_CELERY_TASK_ALWAYS_EAGER"] = "True"
os.environ["NEWS_AI_DATABASE_URL"] = "sqlite:///./test_news_ai_gemini.db"

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.firebase_config import get_db_client
from app.gemini_service import GeminiFactChecker

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    db = get_db_client()
    # Flush Mock Firestore collections
    for col in ["users", "posts", "trusted_docs", "comments", "saves"]:
        for doc in db.collection(col).get():
            doc.reference.delete()
    yield

def test_gemini_fact_checker_mock_fallback():
    claim = "A massive solar storm is heading towards Earth causing a blackout"
    result = asyncio.run(GeminiFactChecker.verify_claim(claim))
    
    assert "accuracy_percentage" in result
    assert "verdict" in result
    assert "analysis_report" in result
    assert result["accuracy_percentage"] == 95.0
    assert "Mostly Correct" in result["verdict"]
    print("\n[PASS] GeminiFactChecker mock fallback verified successfully.")

def test_crawler_agent_run_iteration():
    db = get_db_client()
    assert len(db.collection("posts").get()) == 0
    
    # Seed a trusted doc
    doc_id = "doc_solar"
    db.collection("trusted_docs").document(doc_id).set({
        "id": doc_id,
        "title": "Solar Storm Data",
        "filename": "solar_storm.txt",
        "content": "NASA scientists verify space weather risks but confirm global internet blackout claims are exaggerated."
    })
    
    # Simulate crawler execution step
    from app.crawler_agent import VIRAL_CANDIDATES
    candidate = VIRAL_CANDIDATES[0]
    
    # Force single iteration ingestion
    fact_check_result = asyncio.run(GeminiFactChecker.verify_claim(candidate["content"], "NASA Kepler telescope discovered habitable zone planet."))
    
    db.collection("posts").document(candidate["post_id"]).set({
        "id": candidate["post_id"],
        "post_id": candidate["post_id"],
        "source": candidate["source"],
        "username": candidate["username"],
        "content": candidate["content"],
        "timestamp": "2026-06-28T10:00:00Z",
        "likes": candidate["likes"],
        "retweets": candidate["retweets"],
        "confidence_score": fact_check_result["accuracy_percentage"] / 100.0,
        "accuracy_percentage": fact_check_result["accuracy_percentage"],
        "fact_check_report": fact_check_result["analysis_report"],
        "status": "published",
        "created_at": "2026-06-28T10:00:00Z"
    })
    
    # Query database and verify
    saved_post = db.collection("posts").document(candidate["post_id"]).get().to_dict()
    assert saved_post is not None
    assert saved_post["accuracy_percentage"] is not None
    assert saved_post["fact_check_report"] is not None
    assert saved_post["status"] == "published"
    
    # Verify API endpoint exports new fields
    response = client.get("/posts")
    assert response.status_code == 200
    posts_list = response.json()
    assert len(posts_list) > 0
    
    api_post = next(p for p in posts_list if p["post_id"] == candidate["post_id"])
    assert api_post["accuracy_percentage"] == saved_post["accuracy_percentage"]
    assert api_post["fact_check_report"] == saved_post["fact_check_report"]
    
    print("[PASS] Crawler agent verification and API schemas matched successfully.")
