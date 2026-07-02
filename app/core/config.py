import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "News AI - Ingestion & Verification Engine"
    
    # Paths (relative to app/core/config.py -> resolving to project root)
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    TRUSTED_DOCS_DIR: Path = BASE_DIR / "data" / "trusted_docs"
    GENERATED_VIDEOS_DIR: Path = BASE_DIR / "data" / "generated_videos"
    GENERATED_IMAGES_DIR: Path = BASE_DIR / "data" / "generated_images"
    
    # SQLite Database
    DATABASE_URL: str = "sqlite:///./news_ai.db"
    
    # Celery & Redis settings
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    CELERY_TASK_ALWAYS_EAGER: bool = False
    
    # Confidence Score Threshold
    CONFIDENCE_THRESHOLD: float = 0.95
    
    model_config = SettingsConfigDict(env_prefix="NEWS_AI_")

try:
    settings = Settings()
except Exception as e:
    import sys
    print(f"WARNING: Settings validation failed, using safe fallback defaults: {e}", file=sys.stderr)
    class FallbackSettings:
        PROJECT_NAME = "News AI - Ingestion & Verification Engine"
        BASE_DIR = Path(__file__).resolve().parent.parent.parent
        TRUSTED_DOCS_DIR = BASE_DIR / "data" / "trusted_docs"
        GENERATED_VIDEOS_DIR = BASE_DIR / "data" / "generated_videos"
        GENERATED_IMAGES_DIR = BASE_DIR / "data" / "generated_images"
        DATABASE_URL = "sqlite:///./news_ai.db"
        CELERY_BROKER_URL = "redis://localhost:6379/0"
        CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
        CELERY_TASK_ALWAYS_EAGER = True
        CONFIDENCE_THRESHOLD = 0.95
    settings = FallbackSettings()

# Ensure directories exist
try:
    settings.TRUSTED_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    settings.GENERATED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    settings.GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (settings.BASE_DIR / "tests").mkdir(parents=True, exist_ok=True)
except Exception as e:
    import sys
    print(f"WARNING: Failed to create directories: {e}", file=sys.stderr)
