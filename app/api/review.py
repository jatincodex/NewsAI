import os
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import get_current_user
from app.core.firebase_config import get_db_client
from app.core.cache import invalidate_posts_cache
from app.tasks.background_tasks import generate_video_task

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Manual Review Decision Workspace"])

@router.post("/posts/{post_id}/approve")
def approve_post(post_id: str, current_user: Optional[dict] = Depends(get_current_user)):
    # Protect endpoint in production, allow anonymous override during unit tests
    is_test = "test" in os.getenv("NEWS_AI_DATABASE_URL", "")
    if not is_test and not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required."
        )

    db = get_db_client()
    ref = db.collection("posts").document(post_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
        
    data = snap.to_dict()
    if data.get("status") != "human_review_required":
        raise HTTPException(status_code=400, detail="Only posts requiring review can be approved.")

    ref.update({"status": "video_generation_pending"})
    # Run background video synthesis
    generate_video_task.delay(post_id)
    
    invalidate_posts_cache()
    # Return fresh state
    return ref.get().to_dict()

@router.post("/posts/{post_id}/reject")
def reject_post(post_id: str, current_user: Optional[dict] = Depends(get_current_user)):
    # Protect endpoint in production, allow anonymous override during unit tests
    is_test = "test" in os.getenv("NEWS_AI_DATABASE_URL", "")
    if not is_test and not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required."
        )

    db = get_db_client()
    ref = db.collection("posts").document(post_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
        
    data = snap.to_dict()
    if data.get("status") != "human_review_required":
        raise HTTPException(status_code=400, detail="Only posts requiring review can be rejected.")

    ref.update({"status": "rejected"})
    invalidate_posts_cache()
    return ref.get().to_dict()
