import os
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status

from app.core.config import settings
from app.api import auth, posts, messaging, trusted, review, users, comments, system
from app.crawler_agent import run_crawler_task, stop_crawler

logger = logging.getLogger(__name__)

# --- 1. LIFESPAN EVENT HANDLER ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: spawn async background crawler task
    crawler_task = asyncio.create_task(run_crawler_task(15))
    logger.info("FastAPI lifespan startup completed.")
    yield
    # Shutdown: set cancel triggers and cancel background loop
    stop_crawler()
    crawler_task.cancel()
    try:
        await crawler_task
    except asyncio.CancelledError:
        pass
    logger.info("FastAPI lifespan shutdown completed.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Instagram-style news container platform with verification and reels synthesis.",
    lifespan=lifespan
)



# Register modular api routers
app.include_router(auth.router)
app.include_router(posts.router)
app.include_router(messaging.router)
app.include_router(trusted.router)
app.include_router(review.router)
app.include_router(users.router)
app.include_router(comments.router)
app.include_router(system.router)

from app.api import compat
app.include_router(compat.router)
