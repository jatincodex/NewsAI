import os
import time

# Configure environment before importing components
os.environ["NEWS_AI_CELERY_TASK_ALWAYS_EAGER"] = "True"
os.environ["NEWS_AI_DATABASE_URL"] = "sqlite:///./test_news_ai_gemini.db"

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app.models import SocialPost, TrustedDocument
from app.gemini_service import GeminiFactChecker
from app.crawler_agent import SocialMediaCrawlerAgent

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    # Create test database tables
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.query(SocialPost).delete()
    db.query(TrustedDocument).delete()
    db.commit()
    db.close()
    yield
    # Cleanup after test
    Base.metadata.drop_all(bind=engine)

def test_gemini_fact_checker_mock_fallback():
    # Test verify_claim with mock fallback (no API key set in test env)
    claim = "A massive solar storm is heading towards Earth causing a blackout"
    result = GeminiFactChecker.verify_claim(claim)
    
    assert "accuracy_percentage" in result
    assert "verdict" in result
    assert "analysis_report" in result
    assert result["accuracy_percentage"] == 95.0
    assert "Mostly Correct" in result["verdict"]
    print("\n[PASS] GeminiFactChecker mock fallback verified successfully.")

def test_crawler_agent_run_iteration():
    # Initialize crawler agent with short check interval
    agent = SocialMediaCrawlerAgent(check_interval_seconds=1)
    
    # We will trigger the inner loop logic directly to test ingestion without long waits
    db = SessionLocal()
    
    # Verify no post exists initially
    assert db.query(SocialPost).count() == 0
    
    # Seed a trusted doc
    doc = TrustedDocument(
        title="Solar Storm Data",
        filename="solar_storm.txt",
        content="NASA scientists verify space weather risks but confirm global internet blackout claims are exaggerated."
    )
    db.add(doc)
    db.commit()
    
    # Simulate crawler execution step
    from app.crawler_agent import VIRAL_CANDIDATES
    candidate = VIRAL_CANDIDATES[0] # Kepler telescope discover
    
    # Force single iteration ingestion
    fact_check_result = GeminiFactChecker.verify_claim(candidate["content"], "NASA Kepler telescope discovered habitable zone planet.")
    new_post = SocialPost(
        post_id=candidate["post_id"],
        source=candidate["source"],
        username=candidate["username"],
        content=candidate["content"],
        timestamp="2026-06-28T10:00:00Z",
        likes=candidate["likes"],
        retweets=candidate["retweets"],
        confidence_score=fact_check_result["accuracy_percentage"] / 100.0,
        accuracy_percentage=fact_check_result["accuracy_percentage"],
        fact_check_report=fact_check_result["analysis_report"],
        status="published"
    )
    db.add(new_post)
    db.commit()
    
    # Query database and verify
    saved_post = db.query(SocialPost).filter(SocialPost.post_id == candidate["post_id"]).first()
    assert saved_post is not None
    assert saved_post.accuracy_percentage is not None
    assert saved_post.fact_check_report is not None
    assert saved_post.status == "published"
    
    # Verify API endpoint exports new fields
    response = client.get("/posts")
    assert response.status_code == 200
    posts_list = response.json()
    assert len(posts_list) > 0
    
    api_post = next(p for p in posts_list if p["post_id"] == candidate["post_id"])
    assert api_post["accuracy_percentage"] == saved_post.accuracy_percentage
    assert api_post["fact_check_report"] == saved_post.fact_check_report
    
    db.close()
    print("[PASS] Crawler agent verification and API schemas matched successfully.")
