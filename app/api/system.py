import os
import shutil
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import require_user
from app.core.firebase_config import get_db_client
from app.core.config import settings
from app.core.cache import invalidate_posts_cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["System Management"])

@router.post("/reset")
def reset_system(user: dict = Depends(require_user)):
    """Wipes the database and clears all local files. Requires authenticated session."""
    # Extra protection check: allow database reset only in development/test environment
    is_prod = os.getenv("NEWS_AI_ENV", "development").lower() == "production"
    if is_prod:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Database resets are forbidden in production environment."
        )

    # Clear local file directories
    for directory in [settings.TRUSTED_DOCS_DIR, settings.GENERATED_VIDEOS_DIR, settings.GENERATED_IMAGES_DIR]:
        if directory.exists():
            try:
                shutil.rmtree(directory)
            except Exception as e:
                logger.error(f"Failed to delete directory {directory}: {e}")
        directory.mkdir(parents=True, exist_ok=True)

    db = get_db_client()
    
    if hasattr(db, "db_path"):
        # SQLite Mock client
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        c = conn.cursor()
        c.execute("DELETE FROM collections")
        conn.commit()
        conn.close()
    else:
        # Real Cloud Firestore client
        for col in ["users", "posts", "comments", "saves", "follows", "messages", "trusted_docs"]:
            for doc in db.collection(col).stream():
                doc.reference.delete()

    invalidate_posts_cache()
    return {"message": "System database reset successfully."}
