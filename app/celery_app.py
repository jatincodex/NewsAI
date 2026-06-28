import os
import logging
from celery import Celery

logger = logging.getLogger(__name__)

# Dynamically decide if we run eager tasks (for test suites) or async workers
always_eager = os.getenv("NEWS_AI_CELERY_TASK_ALWAYS_EAGER", "False").lower() in ("true", "1")
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

logger.info(f"[Celery] Initializing Celery app. Broker: {redis_url}, Always Eager: {always_eager}")

celery_app = Celery(
    "news_ai",
    broker=redis_url,
    backend=redis_url
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_always_eager=always_eager,
    imports=["app.tasks"]
)
