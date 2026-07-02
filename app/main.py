import os
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

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

# Mount static folder for assets
app.mount("/static", StaticFiles(directory=str(settings.BASE_DIR / "static")), name="static")

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    """Middleware to inject standard cache-busting headers for developer ease."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Serve static dashboard landing page
@app.get("/", response_class=HTMLResponse)
def read_root():
    """Serves the News AI Platform (Instagram Clone interface)."""
    index_path = settings.BASE_DIR / "static" / "index.html"
    if not index_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Static landing file static/index.html not found."
        )
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()

# Register modular api routers
app.include_router(auth.router)
app.include_router(posts.router)
app.include_router(messaging.router)
app.include_router(trusted.router)
app.include_router(review.router)
app.include_router(users.router)
app.include_router(comments.router)
app.include_router(system.router)
