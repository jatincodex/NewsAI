import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import require_user
from app.core.firebase_config import get_db_client
from app.core.cache import invalidate_posts_cache
from app.models.schemas import CommentCreate

router = APIRouter(tags=["Comments"])

@router.get("/posts/{post_id}/comments")
def get_comments(post_id: str):
    db = get_db_client()
    snap = db.collection("posts").document(post_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
    post_data = snap.to_dict()

    comments_snaps = db.collection("comments").where("post_id", "==", post_data["id"]).get()
    
    res = []
    # Load commenters avatars and info
    for c in comments_snaps:
        c_data = c.to_dict()
        user_snap = db.collection("users").document(c_data["user_id"]).get()
        user_info = user_snap.to_dict() if user_snap.exists else {}
        res.append({
            "id": c_data["id"],
            "user_id": c_data["user_id"],
            "post_id": c_data["post_id"],
            "text": c_data["text"],
            "username": user_info.get("username", "unknown"),
            "avatar_index": user_info.get("avatar_index", 1),
            "created_at": c_data.get("created_at")
        })
        
    res.sort(key=lambda x: x.get("created_at", ""))
    return res

@router.post("/posts/{post_id}/comments")
def add_comment(post_id: str, payload: CommentCreate, user: dict = Depends(require_user)):
    db = get_db_client()
    snap = db.collection("posts").document(post_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
    post_data = snap.to_dict()

    comment_id = f"com_{uuid.uuid4().hex[:10]}"
    comment_data = {
        "id": comment_id,
        "user_id": user["id"],
        "post_id": post_data["id"],
        "text": payload.text,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    db.collection("comments").document(comment_id).set(comment_data)
    invalidate_posts_cache()
    
    return {
        "id": comment_id,
        "user_id": user["id"],
        "post_id": post_data["id"],
        "text": comment_data["text"],
        "username": user["username"],
        "avatar_index": user["avatar_index"],
        "created_at": comment_data["created_at"]
    }
