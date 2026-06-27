import os
from celery import Celery
from app.config import settings

# Force eager mode dynamically if direct environment variable is present, 
# bypassing any cached singleton issues during pytest collection.
is_eager = settings.CELERY_TASK_ALWAYS_EAGER or os.getenv("NEWS_AI_CELERY_TASK_ALWAYS_EAGER", "").lower() in ("true", "1")

broker_url = "memory://" if is_eager else settings.CELERY_BROKER_URL
result_backend = "cache+memory://" if is_eager else settings.CELERY_RESULT_BACKEND

celery_app = Celery(
    "news_ai_tasks",
    broker=broker_url,
    backend=result_backend
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_always_eager=is_eager,
)

# Auto-discover tasks from app.tasks
celery_app.autodiscover_tasks(["app"], force=True)
