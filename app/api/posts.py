import os
import uuid
import shutil
import logging
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Form, File, UploadFile
from fastapi.responses import FileResponse
from app.core.security import require_user, get_current_user
from app.core.firebase_config import get_db_client
from app.core.config import settings
from app.core.cache import get_cached_posts, set_cached_posts, invalidate_posts_cache
from app.tasks.background_tasks import process_social_post
from app.models.schemas import SocialPostIngestPayload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Posts"])

@router.post("/ingest", status_code=status.HTTP_201_CREATED)
def ingest_social_post(payload: SocialPostIngestPayload, current_user: Optional[dict] = Depends(get_current_user)):
    post_id = payload.post_id.strip()
    if not post_id:
        raise HTTPException(status_code=400, detail="Missing post_id key.")

    db = get_db_client()
    existing = db.collection("posts").document(post_id).get()
    if existing.exists:
        raise HTTPException(status_code=400, detail=f"Post with ID '{post_id}' already ingested.")

    likes = payload.metadata.likes if payload.metadata else 0
    retweets = payload.metadata.retweets if payload.metadata else 0

    post_data = {
        "id": post_id,
        "post_id": post_id,
        "source": payload.source,
        "username": payload.username,
        "content": payload.content,
        "timestamp": payload.timestamp,
        "likes": likes,
        "retweets": retweets,
        "likes_count": likes,
        "confidence_score": 0.0,
        "accuracy_percentage": None,
        "fact_check_report": None,
        "status": "pending",
        "video_path": None,
        "image_path": None,
        "user_id": current_user["id"] if current_user else None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    db.collection("posts").document(post_id).set(post_data)
    invalidate_posts_cache()
    
    # Trigger verification Celery task
    process_social_post.delay(post_id)
    return post_data

@router.post("/posts/create", status_code=status.HTTP_201_CREATED)
def create_custom_post(
    content: str = Form(...),
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(require_user)
):
    post_id = f"custom_{uuid.uuid4().hex[:8]}"
    image_path = None
    video_path = None
    
    if file:
        file_ext = os.path.splitext(file.filename)[1].lower() if file.filename else ""
        content_type = file.content_type or ""
        
        # Save image or video
        if "video" in content_type or file_ext in [".mp4", ".mov", ".avi", ".webm"]:
            filename = f"vid_{post_id}{file_ext or '.mp4'}"
            video_path = str(settings.GENERATED_VIDEOS_DIR / filename)
            try:
                with open(video_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to save video: {e}")
        else:
            filename = f"img_{post_id}{file_ext or '.jpg'}"
            image_path = str(settings.GENERATED_IMAGES_DIR / filename)
            try:
                with open(image_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to save image: {e}")

    post_data = {
        "id": post_id,
        "post_id": post_id,
        "source": "NewsAI",
        "username": user["username"],
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "likes": 0,
        "retweets": 0,
        "likes_count": 0,
        "confidence_score": 0.0,
        "accuracy_percentage": None,
        "fact_check_report": None,
        "status": "pending",
        "video_path": video_path,
        "image_path": image_path,
        "user_id": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    db = get_db_client()
    db.collection("posts").document(post_id).set(post_data)
    invalidate_posts_cache()
    
    # Trigger verification Celery task
    process_social_post.delay(post_id)
    return post_data

@router.get("/posts")
def get_posts(status_filter: Optional[str] = None):
    """Fetch all ingested social media posts (excluding rejected items)."""
    if not status_filter:
        cached = get_cached_posts()
        if cached is not None:
            return cached

    db = get_db_client()
    
    # Optimization: Filter by status at the database layer when possible
    if status_filter:
        snaps = db.collection("posts").where("status", "==", status_filter).get()
    else:
        snaps = db.collection("posts").get()
    
    results = []
    for s in snaps:
        data = s.to_dict()
        if data.get("status") != "rejected":
            results.append(data)

    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    if not status_filter:
        set_cached_posts(results, expire_seconds=30)

    return results

@router.get("/posts/saved")
def get_saved_posts(user: dict = Depends(require_user)):
    """Retrieve bookmarked posts for the current authenticated user."""
    db = get_db_client()
    saves_snaps = db.collection("saves").where("user_id", "==", user["id"]).get()
    saved_ids = [s.to_dict().get("post_id") for s in saves_snaps]
    
    results = []
    if saved_ids:
        post_snaps = db.collection("posts").get()
        for p in post_snaps:
            data = p.to_dict()
            if data.get("id") in saved_ids:
                results.append(data)
                
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results

@router.post("/posts/{post_id}/save")
def save_post(post_id: str, user: dict = Depends(require_user)):
    db = get_db_client()
    snap = db.collection("posts").document(post_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
        
    post_data = snap.to_dict()
    
    # Check if already saved
    existing = db.collection("saves").where("user_id", "==", user["id"]).where("post_id", "==", post_data["id"]).get()
    if existing:
        return {"status": "already_saved"}
        
    save_id = f"save_{uuid.uuid4().hex[:10]}"
    db.collection("saves").document(save_id).set({
        "id": save_id,
        "user_id": user["id"],
        "post_id": post_data["id"],
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    invalidate_posts_cache()
    return {"status": "saved"}

@router.delete("/posts/{post_id}/save")
def unsave_post(post_id: str, user: dict = Depends(require_user)):
    db = get_db_client()
    snap = db.collection("posts").document(post_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
        
    post_data = snap.to_dict()
    
    existing = db.collection("saves").where("user_id", "==", user["id"]).where("post_id", "==", post_data["id"]).get()
    if existing:
        existing[0].reference.delete()
        invalidate_posts_cache()
    return {"status": "unsaved"}

@router.get("/posts/{post_id}")
def get_post_by_id(post_id: str):
    db = get_db_client()
    snap = db.collection("posts").document(post_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
    return snap.to_dict()

@router.post("/posts/{post_id}/like")
def like_post(post_id: str, action: str, user: dict = Depends(require_user)):
    db = get_db_client()
    ref = db.collection("posts").document(post_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
        
    data = snap.to_dict()
    likes = data.get("likes_count", 0)
    if action == "like":
        likes += 1
    elif action == "unlike" and likes > 0:
        likes -= 1
        
    ref.update({"likes_count": likes})
    invalidate_posts_cache()
    return {"likes_count": likes}

@router.get("/posts/{post_id}/video")
def serve_post_video(post_id: str):
    db = get_db_client()
    snap = db.collection("posts").document(post_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
    video_path = snap.to_dict().get("video_path")
    if not video_path:
        raise HTTPException(status_code=404, detail="Video path missing.")
    
    # Path Traversal vulnerability fix: ensure video is under GENERATED_VIDEOS_DIR
    resolved_path = os.path.abspath(video_path)
    base_dir = os.path.abspath(str(settings.GENERATED_VIDEOS_DIR))
    if not resolved_path.startswith(base_dir):
        raise HTTPException(status_code=403, detail="Access denied.")
        
    return FileResponse(resolved_path)

@router.get("/posts/{post_id}/image")
def serve_post_image(post_id: str):
    db = get_db_client()
    snap = db.collection("posts").document(post_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
    image_path = snap.to_dict().get("image_path")
    if not image_path:
        raise HTTPException(status_code=404, detail="Image path missing.")
        
    # Path Traversal vulnerability fix: ensure image is under GENERATED_IMAGES_DIR
    resolved_path = os.path.abspath(image_path)
    base_dir = os.path.abspath(str(settings.GENERATED_IMAGES_DIR))
    if not resolved_path.startswith(base_dir):
        raise HTTPException(status_code=403, detail="Access denied.")
        
    return FileResponse(resolved_path)

@router.get("/explore")
def explore_posts(query: Optional[str] = None):
    db = get_db_client()
    snaps = db.collection("posts").get()
    
    results = []
    for s in snaps:
        data = s.to_dict()
        if data.get("status") != "rejected":
            if not query or query.lower() in data.get("content", "").lower():
                results.append(data)
                
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results
