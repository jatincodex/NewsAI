import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import require_user
from app.core.firebase_config import get_db_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])

@router.post("/{username}/follow")
def follow_user(username: str, current_user: dict = Depends(require_user)):
    db = get_db_client()
    # Get target user
    snaps = db.collection("users").where("username", "==", username).get()
    if not snaps:
        raise HTTPException(status_code=404, detail="Target user not found.")
    target_user = snaps[0].to_dict()
    
    if target_user["id"] == current_user["id"]:
        raise HTTPException(status_code=400, detail="You cannot follow yourself.")

    follow_snaps = db.collection("follows").where("follower_id", "==", current_user["id"]).where("followed_id", "==", target_user["id"]).get()
    
    if follow_snaps:
        follow_snaps[0].reference.delete()
        return {"status": "unfollowed"}
    else:
        doc_id = f"fol_{uuid.uuid4().hex[:10]}"
        db.collection("follows").document(doc_id).set({
            "id": doc_id,
            "follower_id": current_user["id"],
            "followed_id": target_user["id"],
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        return {"status": "followed"}

@router.get("/{username}/profile")
def get_user_profile(username: str, current_user: dict = Depends(require_user)):
    db = get_db_client()
    snaps = db.collection("users").where("username", "==", username).get()
    if not snaps:
        raise HTTPException(status_code=404, detail="User not found.")
    target_user = snaps[0].to_dict()

    # Query metrics
    posts_snaps = db.collection("posts").where("username", "==", username).get()
    posts_count = len(posts_snaps)

    followers_snaps = db.collection("follows").where("followed_id", "==", target_user["id"]).get()
    followers_count = len(followers_snaps)

    following_snaps = db.collection("follows").where("follower_id", "==", target_user["id"]).get()
    following_count = len(following_snaps)

    is_following = any(f.to_dict().get("follower_id") == current_user["id"] for f in followers_snaps)

    return {
        "id": target_user["id"],
        "username": target_user["username"],
        "display_name": target_user.get("display_name"),
        "bio": target_user.get("bio", ""),
        "avatar_index": target_user.get("avatar_index", 1),
        "posts_count": posts_count,
        "followers_count": followers_count,
        "following_count": following_count,
        "is_following": is_following
    }

@router.get("")
def list_users():
    db = get_db_client()
    snaps = db.collection("users").get()
    return [s.to_dict() for s in snaps]
