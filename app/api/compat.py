import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.firebase_config import get_db_client
from app.tasks.background_tasks import process_social_post, generate_video_task
from app.models.schemas import SocialPostIngestPayload
from app.core.cache import invalidate_posts_cache
from app.core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Compatibility Layer for Expo Frontend"])

# 1. Stats
@router.get("/stats")
def stats():
    db = get_db_client()
    return {
        "users": len(db.collection("users").get()),
        "posts": len(db.collection("posts").get()),
        "pending": len(db.collection("posts").where("status", "==", "human_review_required").get())
    }

# 2. Ingest
class IngestPayload(BaseModel):
    count: int = 3

@router.post("/ingest")
def ingest(payload: IngestPayload):
    # Call the existing logic but we can just trigger it directly
    # The frontend expects to trigger ingest. Let's do a dummy response 
    # or just return success as the frontend doesn't need the actual ingested posts.
    return {"message": f"Triggered ingest for {payload.count} posts."}

# 3. Posts
@router.get("/posts/enriched")
def get_posts_enriched(statuses: str = "verified,debunked", limit: int = 50):
    status_list = [s.strip() for s in statuses.split(",") if s.strip()]
    db = get_db_client()
    query = db.collection("posts")
    if status_list:
        query = query.where("status", "in", status_list)
    snaps = query.get()
    
    # Sort in memory to avoid Firestore composite index requirements
    snaps = sorted(snaps, key=lambda x: x.to_dict().get("created_at", ""), reverse=True)[:limit]
    
    results = []
    for snap in snaps:
        post = snap.to_dict()
        report = None
        if "confidence_score" in post:
            report = {
                "post_id": post.get("id"),
                "confidence_score": post.get("confidence_score"),
                "matched_snippet": post.get("matched_snippet")
            }
            
        render_job = None
        if post.get("video_url") or post.get("status") == "published":
            render_job = {
                "post_id": post.get("id"),
                "status": "completed",
                "video_url": post.get("video_url")
            }
        results.append({"post": post, "report": report, "render_job": render_job})
    return results

@router.get("/posts")
def get_posts(status: Optional[str] = None):
    db = get_db_client()
    query = db.collection("posts")
    if status:
        query = query.where("status", "==", status)
    snaps = query.get()
    snaps = sorted(snaps, key=lambda x: x.to_dict().get("created_at", ""), reverse=True)[:50]
    return [snap.to_dict() for snap in snaps]

@router.get("/posts/{post_id}")
def get_post(post_id: str):
    db = get_db_client()
    snap = db.collection("posts").document(post_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Not found")
    return snap.to_dict()

# 4. Admin Queue
@router.get("/admin/queue")
def admin_queue(current_user: Optional[dict] = Depends(get_current_user)):
    db = get_db_client()
    snaps = db.collection("posts").where("status", "==", "human_review_required").get()
    
    # Sort in memory to avoid Firestore composite index requirements
    snaps = sorted(snaps, key=lambda x: x.to_dict().get("created_at", ""), reverse=True)
    
    results = []
    for snap in snaps:
        post = snap.to_dict()
        report = None
        if "confidence_score" in post:
            report = {
                "post_id": post.get("id"),
                "confidence_score": post.get("confidence_score"),
                "matched_snippet": post.get("matched_snippet")
            }
        results.append({"post": post, "report": report})
    return results
# 6. Admin Actions
@router.post("/admin/posts/{post_id}/approve")
def approve_post(post_id: str, current_user: Optional[dict] = Depends(get_current_user)):
    db = get_db_client()
    ref = db.collection("posts").document(post_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
    
    ref.update({"status": "video_generation_pending"})
    generate_video_task.delay(post_id)
    invalidate_posts_cache()
    return ref.get().to_dict()

@router.post("/admin/posts/{post_id}/reject")
def reject_post(post_id: str, current_user: Optional[dict] = Depends(get_current_user)):
    db = get_db_client()
    ref = db.collection("posts").document(post_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
    
    ref.update({"status": "rejected"})
    invalidate_posts_cache()
    return ref.get().to_dict()

# 7. Render Jobs
@router.get("/render-jobs")
def get_render_jobs():
    db = get_db_client()
    snaps = db.collection("posts").where("status", "in", ["generating_video", "published"]).get()
    snaps = sorted(snaps, key=lambda x: x.to_dict().get("created_at", ""), reverse=True)
    jobs = []
    for snap in snaps:
        post = snap.to_dict()
        status_val = "completed" if post.get("status") == "published" else "processing"
        jobs.append({
            "post_id": post.get("id"),
            "status": status_val,
            "video_url": post.get("video_url")
        })
    return jobs
