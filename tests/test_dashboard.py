import os

os.environ["NEWS_AI_CELERY_TASK_ALWAYS_EAGER"] = "True"
os.environ["NEWS_AI_DATABASE_URL"] = "sqlite:///./test_news_ai_dash.db"

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
    if os.path.exists("test_news_ai_dash.db"):
        try:
            os.remove("test_news_ai_dash.db")
        except:
            pass

def test_dashboard_and_static_routes():
    # 1. Verify index HTML is served on root path
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "NewsAI" in response.text
    assert "id=\"video-modal\"" in response.text
    print("\n[PASS] Root path GET / successfully serves the HTML Dashboard.")

    # 2. Verify static stylesheet is served
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "glow-sphere" in response.text
    print("[PASS] Static stylesheet served successfully.")

    # 3. Verify static javascript controller is served
    response = client.get("/static/app.js")
    assert response.status_code == 200
    # On some systems/fastapi versions, the JS mime type might be application/javascript or text/javascript
    assert "javascript" in response.headers["content-type"]
    assert "openReelPlayer" in response.text
    print("[PASS] Static javascript controller served successfully.")
