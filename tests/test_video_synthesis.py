import os
import shutil
from pathlib import Path

# Configure environment before importing any app components
os.environ["NEWS_AI_CELERY_TASK_ALWAYS_EAGER"] = "True"
os.environ["NEWS_AI_DATABASE_URL"] = "sqlite:///./test_news_ai_video.db"

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
    
    if os.path.exists("test_news_ai_video.db"):
        os.remove("test_news_ai_video.db")
        
    # Clear generated test videos
    if settings.GENERATED_VIDEOS_DIR.exists():
        shutil.rmtree(settings.GENERATED_VIDEOS_DIR)

def test_video_synthesis_pipeline():
    # 1. Seed trusted reference data
    doc_payload = {
        "title": "NASA Breakthrough Announcement",
        "content": "NASA Kepler telescope discovered an Earth-sized planet orbiting in the habitable zone of a distant star."
    }
    response = client.post("/trusted-docs", json=doc_payload)
    assert response.status_code == 201
    
    # 2. Ingest matching post that passes confidence gate (Score >= 0.95)
    matching_post = {
        "source": "X",
        "post_id": "video_test_101",
        "username": "space_hub",
        "content": "NASA Kepler telescope discovered an Earth-sized planet orbiting in the habitable zone of a distant star.",
        "timestamp": "2026-06-18T20:10:00Z"
    }
    
    # Ingesting triggers process_social_post which chains generate_video_task in eager mode
    response = client.post("/ingest", json=matching_post)
    assert response.status_code == 201
    
    # 3. Retrieve processed details
    response = client.get("/posts/video_test_101")
    assert response.status_code == 200
    post_data = response.json()
    
    # Verify confidence gate passed
    assert post_data["confidence_score"] == 1.0
    
    # Verify event-driven status transitioned all the way to published
    assert post_data["status"] == "published"
    assert post_data["video_path"] is not None
    
    video_filepath = Path(post_data["video_path"])
    assert video_filepath.exists()
    assert video_filepath.stat().st_size > 0
    print(f"\n[PASS] Video successfully synthesized at: {video_filepath} (Size: {video_filepath.stat().st_size} bytes)")
    
    # 4. Verify retrieving the video file via the GET /posts/{post_id}/video route
    video_response = client.get("/posts/video_test_101/video")
    assert video_response.status_code == 200
    assert video_response.headers["content-type"] == "video/mp4"
    assert len(video_response.content) == video_filepath.stat().st_size
    print("[PASS] Video streaming endpoint verified successfully.")
