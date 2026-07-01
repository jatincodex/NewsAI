import os
import time
import uuid
import random
import shutil
import logging
import json
import asyncio
from typing import List, Optional
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status, Header, Form, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.auth import AuthHandler
from app.tasks import process_social_post, generate_video_task
from app.crawler_agent import run_crawler_task, stop_crawler
from app.cache import get_cached_posts, set_cached_posts, invalidate_posts_cache
from app.firebase_config import get_db_client, verify_token

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
    """Middle ware to inject standard cache-busting headers for developer ease."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# --- 2. AUTHENTICATION DEPENDENCIES ---

def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """Dependency to retrieve the currently logged in user context via Firebase ID tokens."""
    if not authorization:
        return None
        
    token = authorization
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        
    try:
        decoded = verify_token(token)
        uid = decoded.get("uid") or decoded.get("user_id")
        email = decoded.get("email")
        if not uid or not email:
            return None
            
        db = get_db_client()
        user_ref = db.collection("users").document(uid)
        snap = user_ref.get()
        if snap.exists:
            return snap.to_dict()
            
        # First-time OAuth login handler: create user document on the fly
        username = decoded.get("username") or email.split("@")[0]
        display_name = decoded.get("name") or decoded.get("display_name") or username.capitalize()
        user_data = {
            "id": uid,
            "username": username,
            "email": email,
            "display_name": display_name,
            "bio": "",
            "avatar_index": random.randint(1, 8),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        user_ref.set(user_data)
        return user_data
    except Exception as e:
        logger.error(f"Authentication token decoding failed: {e}")
        return None

def require_user(user: Optional[dict] = Depends(get_current_user)) -> dict:
    """Dependency that raises 401 if user is not authenticated."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required."
        )
    return user


# --- 3. STATIC ASSETS ---

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


# --- 4. SIGNUP & LOGIN APIS ---

class UserSignupPayload:
    def __init__(self, username: str, email: str, password: str, display_name: Optional[str] = None):
        self.username = username
        self.email = email
        self.password = password
        self.display_name = display_name

@app.post("/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(payload: dict):
    username = payload.get("username", "").strip()
    email = payload.get("email", "").strip()
    password = payload.get("password", "")
    display_name = payload.get("display_name", "").strip()

    if not username or not email or not password:
        raise HTTPException(status_code=400, detail="Missing required signup fields.")

    if not email.endswith("@gmail.com"):
        raise HTTPException(status_code=400, detail="Only @gmail.com Gmail addresses are supported.")

    db = get_db_client()
    # Check duplicate email
    email_docs = db.collection("users").where("email", "==", email).get()
    if email_docs:
        raise HTTPException(status_code=400, detail="Gmail address already registered.")

    # Check duplicate username
    user_docs = db.collection("users").where("username", "==", username).get()
    if user_docs:
        raise HTTPException(status_code=400, detail="Username already taken.")

    uid = f"uid_{uuid.uuid4().hex[:12]}"
    hashed_password = AuthHandler.hash_password(password)

    user_data = {
        "id": uid,
        "username": username,
        "email": email,
        "hashed_password": hashed_password,
        "display_name": display_name or username.capitalize(),
        "bio": "",
        "avatar_index": random.randint(1, 8),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    db.collection("users").document(uid).set(user_data)
    token = AuthHandler.generate_token(uid, username)
    return {
        "token": token,
        "user": {
            "id": uid,
            "username": username,
            "email": email,
            "display_name": user_data["display_name"],
            "avatar_index": user_data["avatar_index"]
        }
    }

@app.post("/auth/login")
async def login(payload: dict):
    user_or_email = (payload.get("username_or_email") or payload.get("username") or "").strip()
    password = payload.get("password", "")

    db = get_db_client()
    user_data = None
    
    # Check if email search
    if "@" in user_or_email:
        snaps = db.collection("users").where("email", "==", user_or_email).get()
    else:
        snaps = db.collection("users").where("username", "==", user_or_email).get()

    if snaps:
        user_data = snaps[0].to_dict()

    if not user_data or not AuthHandler.verify_password(password, user_data.get("hashed_password", "")):
        raise HTTPException(status_code=401, detail="Invalid username/email or password.")

    token = AuthHandler.generate_token(user_data["id"], user_data["username"])
    return {
        "token": token,
        "user": {
            "id": user_data["id"],
            "username": user_data["username"],
            "email": user_data["email"],
            "display_name": user_data.get("display_name"),
            "avatar_index": user_data.get("avatar_index")
        }
    }

@app.post("/auth/google")
async def google_login(payload: dict):
    email = payload.get("email", "").strip()
    display_name = payload.get("display_name", "").strip()

    if not email.endswith("@gmail.com"):
        raise HTTPException(status_code=400, detail="Only @gmail.com Google accounts allowed.")

    db = get_db_client()
    snaps = db.collection("users").where("email", "==", email).get()
    
    if snaps:
        user_data = snaps[0].to_dict()
    else:
        # Create Google signup user on the fly
        uid = f"uid_g_{uuid.uuid4().hex[:10]}"
        username = email.split("@")[0]
        user_data = {
            "id": uid,
            "username": username,
            "email": email,
            "display_name": display_name or username.capitalize(),
            "bio": "",
            "avatar_index": random.randint(1, 8),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        db.collection("users").document(uid).set(user_data)

    token = AuthHandler.generate_token(user_data["id"], user_data["username"])
    return {
        "token": token,
        "user": {
            "id": user_data["id"],
            "username": user_data["username"],
            "email": user_data["email"],
            "display_name": user_data.get("display_name"),
            "avatar_index": user_data.get("avatar_index")
        }
    }

@app.post("/auth/forgot-password")
async def forgot_password(payload: dict):
    email = payload.get("email", "").strip()
    db = get_db_client()
    snaps = db.collection("users").where("email", "==", email).get()
    if not snaps:
        raise HTTPException(status_code=404, detail="No registered account found with that email.")
    
    user_ref = snaps[0].reference
    # Generate 6 digit pin
    code = f"{random.randint(100000, 999999)}"
    expires = int(time.time()) + 600 # 10 mins
    
    user_ref.update({
        "reset_code": code,
        "reset_code_expires": expires
    })
    
    # Print reset key to standard console for visual testing
    print(f"\n=====================================")
    print(f"PASSWORD RESET REQUEST")
    print(f"Email: {email}")
    print(f"Reset Code: {code}")
    print(f"=====================================\n", flush=True)

    return {"message": "Reset PIN code issued successfully.", "reset_code": code}

@app.post("/auth/reset-password")
async def reset_password(payload: dict):
    email = payload.get("email", "").strip()
    code = str(payload.get("code") or payload.get("reset_code") or "").strip()
    new_password = payload.get("new_password", "")

    db = get_db_client()
    snaps = db.collection("users").where("email", "==", email).get()
    if not snaps:
        raise HTTPException(status_code=404, detail="Email not registered.")

    user_ref = snaps[0].reference
    user_data = snaps[0].to_dict()

    saved_code = user_data.get("reset_code")
    expiry = user_data.get("reset_code_expires", 0)

    if not saved_code or saved_code != code or int(time.time()) > expiry:
        raise HTTPException(status_code=400, detail="Invalid or expired reset PIN code.")

    hashed_password = AuthHandler.hash_password(new_password)
    user_ref.update({
        "hashed_password": hashed_password,
        "reset_code": None,
        "reset_code_expires": None
    })
    return {"message": "Password reset successfully."}

@app.get("/auth/me")
def get_me(user: dict = Depends(require_user)):
    return user

@app.post("/auth/update")
def update_profile(payload: dict, user: dict = Depends(require_user)):
    db = get_db_client()
    user_ref = db.collection("users").document(user["id"])
    
    updates = {}
    if payload.get("display_name") is not None:
        updates["display_name"] = payload["display_name"].strip()
    if payload.get("bio") is not None:
        updates["bio"] = payload["bio"].strip()
    if payload.get("avatar_index") is not None:
        avatar = int(payload["avatar_index"])
        if 1 <= avatar <= 8:
            updates["avatar_index"] = avatar
            
    if updates:
        user_ref.update(updates)
        user.update(updates)
        
    return user


# --- 5. SOCIAL FEED & INGESTION APIS ---

@app.post("/ingest", status_code=status.HTTP_201_CREATED)
def ingest_social_post(payload: dict, current_user: Optional[dict] = Depends(get_current_user)):
    post_id = payload.get("post_id", "").strip()
    if not post_id:
        raise HTTPException(status_code=400, detail="Missing post_id key.")

    db = get_db_client()
    existing = db.collection("posts").document(post_id).get()
    if existing.exists:
        raise HTTPException(status_code=400, detail=f"Post with ID '{post_id}' already ingested.")

    metadata = payload.get("metadata", {}) or {}
    likes = metadata.get("likes") or 0
    retweets = metadata.get("retweets") or 0

    post_data = {
        "id": post_id,
        "post_id": post_id,
        "source": payload.get("source", "X"),
        "username": payload.get("username", "anonymous"),
        "content": payload.get("content", ""),
        "timestamp": payload.get("timestamp", datetime.now(timezone.utc).isoformat()),
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

@app.post("/posts/create", status_code=status.HTTP_201_CREATED)
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

@app.get("/posts")
def get_posts(status_filter: Optional[str] = None):
    """Fetch all ingested social media posts (excluding rejected items)."""
    if not status_filter:
        cached = get_cached_posts()
        if cached is not None:
            return cached

    db = get_db_client()
    snaps = db.collection("posts").get()
    
    results = []
    for s in snaps:
        data = s.to_dict()
        if data.get("status") != "rejected":
            if not status_filter or data.get("status") == status_filter:
                results.append(data)

    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    if not status_filter:
        set_cached_posts(results, expire_seconds=30)

    return results

@app.get("/posts/saved")
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

@app.post("/posts/{post_id}/save")
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

@app.delete("/posts/{post_id}/save")
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


@app.get("/posts/{post_id}")
def get_post_by_id(post_id: str):
    db = get_db_client()
    snap = db.collection("posts").document(post_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
    return snap.to_dict()

@app.post("/posts/{post_id}/like")
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


# --- 6. MEDIA SERVING APIS ---

@app.get("/posts/{post_id}/video")
def serve_post_video(post_id: str):
    db = get_db_client()
    snap = db.collection("posts").document(post_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
    video_path = snap.to_dict().get("video_path")
    if not video_path:
        raise HTTPException(status_code=404, detail="Video path missing.")
    return FileResponse(video_path)

@app.get("/posts/{post_id}/image")
def serve_post_image(post_id: str):
    db = get_db_client()
    snap = db.collection("posts").document(post_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Post not found.")
    image_path = snap.to_dict().get("image_path")
    if not image_path:
        raise HTTPException(status_code=404, detail="Image path missing.")
    return FileResponse(image_path)


# --- 7. TRUSTED DOCUMENT SOURCES APIS ---

@app.post("/trusted-docs", status_code=status.HTTP_201_CREATED)
def create_trusted_document(payload: dict):
    title = payload.get("title", "").strip()
    content = payload.get("content", "")
    if not title or not content:
        raise HTTPException(status_code=400, detail="Missing doc attributes.")

    filename = f"{title.lower().replace(' ', '_')}_{uuid.uuid4().hex[:4]}.txt"
    settings.TRUSTED_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = settings.TRUSTED_DOCS_DIR / filename
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Filesystem write failed: {e}")

    db = get_db_client()
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    doc_data = {
        "id": doc_id,
        "title": title,
        "filename": filename,
        "content": content,
        "uploaded_at": datetime.now(timezone.utc).isoformat()
    }
    
    db.collection("trusted_docs").document(doc_id).set(doc_data)
    return doc_data

@app.get("/trusted-docs")
def list_trusted_documents():
    db = get_db_client()
    snaps = db.collection("trusted_docs").get()
    return [s.to_dict() for s in snaps]


# --- 8. MANUAL REVIEW DECISION WORKSPACE ---

@app.post("/posts/{post_id}/approve")
def approve_post(post_id: str):
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

@app.post("/posts/{post_id}/reject")
def reject_post(post_id: str):
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


# --- 9. SOCIAL USER INTERACTIONS APIS ---

@app.post("/users/{username}/follow")
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

@app.get("/users/{username}/profile")
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


# --- 10. COMMENTS APIS ---

@app.get("/posts/{post_id}/comments")
def get_comments(post_id: str):
    db = get_db_client()
    # Resolve post doc_id
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

@app.post("/posts/{post_id}/comments")
def add_comment(post_id: str, payload: dict, user: dict = Depends(require_user)):
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
        "text": payload.get("text", ""),
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


# --- 11. E2EE KEY MANAGEMENT ---

@app.post("/keys/publish")
def publish_public_key(payload: dict, user: dict = Depends(require_user)):
    """Store the user's RSA public key (JWK format) on the server."""
    public_key_jwk = payload.get("public_key_jwk")
    if not public_key_jwk:
        raise HTTPException(status_code=400, detail="Missing public_key_jwk field.")
    db = get_db_client()
    db.collection("users").document(user["id"]).update({"public_key_jwk": public_key_jwk})
    return {"status": "ok"}

@app.get("/keys/{username}")
def get_public_key(username: str):
    """Fetch a user's RSA public key by username."""
    db = get_db_client()
    snaps = db.collection("users").where("username", "==", username).get()
    if not snaps:
        raise HTTPException(status_code=404, detail="User not found.")
    user_data = snaps[0].to_dict()
    key = user_data.get("public_key_jwk")
    if not key:
        raise HTTPException(status_code=404, detail="User has not published a public key yet.")
    return {"username": username, "public_key_jwk": key}


# --- 12. DIRECT MESSAGING (DMs) — E2EE UPGRADED ---

@app.get("/messages")
def get_messages(with_user: str, user: dict = Depends(require_user)):
    db = get_db_client()
    snaps = db.collection("users").where("username", "==", with_user).get()
    if not snaps:
        raise HTTPException(status_code=404, detail="Target user not found.")
    other_user = snaps[0].to_dict()

    all_msgs = db.collection("messages").get()
    res = []
    for m in all_msgs:
        data = m.to_dict()
        s_id = data.get("sender_id")
        r_id = data.get("recipient_id")
        if (s_id == user["id"] and r_id == other_user["id"]) or \
           (s_id == other_user["id"] and r_id == user["id"]):
            res.append({
                "id": data["id"],
                "sender_id": s_id,
                "recipient_id": r_id,
                # E2EE fields — ciphertext only, server never sees plaintext
                "encrypted_text": data.get("encrypted_text"),
                "encrypted_key_for_sender": data.get("encrypted_key_for_sender"),
                "encrypted_key_for_recipient": data.get("encrypted_key_for_recipient"),
                # Fallback plaintext for legacy messages
                "text": data.get("text", ""),
                "is_encrypted": data.get("is_encrypted", False),
                "sender_username": user["username"] if s_id == user["id"] else other_user["username"],
                "recipient_username": other_user["username"] if s_id == user["id"] else user["username"],
                "created_at": data.get("created_at")
            })

    res.sort(key=lambda x: x.get("created_at", ""))
    return res

@app.post("/messages")
def send_message(payload: dict, user: dict = Depends(require_user)):
    recipient_username = payload.get("recipient_username", "").strip()

    db = get_db_client()
    snaps = db.collection("users").where("username", "==", recipient_username).get()
    if not snaps:
        raise HTTPException(status_code=404, detail="Recipient user not found.")
    recipient = snaps[0].to_dict()

    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    msg_data = {
        "id": msg_id,
        "sender_id": user["id"],
        "recipient_id": recipient["id"],
        "created_at": now,
    }

    # E2EE path — store only ciphertext
    if payload.get("encrypted_text"):
        msg_data.update({
            "encrypted_text": payload["encrypted_text"],
            "encrypted_key_for_sender": payload.get("encrypted_key_for_sender"),
            "encrypted_key_for_recipient": payload.get("encrypted_key_for_recipient"),
            "text": "",
            "is_encrypted": True,
        })
    else:
        # Legacy plaintext fallback
        msg_data.update({"text": payload.get("text", ""), "is_encrypted": False})

    db.collection("messages").document(msg_id).set(msg_data)
    return {**msg_data, "sender_username": user["username"], "recipient_username": recipient["username"]}


# --- 13. GROUP CHATS — E2EE ---

@app.post("/groups", status_code=201)
def create_group(payload: dict, user: dict = Depends(require_user)):
    """Create a new encrypted group chat."""
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required.")
    member_usernames = payload.get("members", [])  # list of usernames to invite

    db = get_db_client()
    group_id = f"grp_{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()

    # Resolve member user IDs
    member_ids = [user["id"]]  # creator is always first member
    for uname in member_usernames:
        uname = uname.strip()
        if not uname or uname == user["username"]:
            continue
        snaps = db.collection("users").where("username", "==", uname).get()
        if snaps:
            uid = snaps[0].to_dict()["id"]
            if uid not in member_ids:
                member_ids.append(uid)

    if len(member_ids) > 50:
        raise HTTPException(status_code=400, detail="Groups are limited to 50 members.")

    group_data = {
        "id": group_id,
        "name": name,
        "creator_id": user["id"],
        "member_ids": member_ids,
        "created_at": now,
    }
    db.collection("groups").document(group_id).set(group_data)
    return group_data

@app.get("/groups")
def list_groups(user: dict = Depends(require_user)):
    """List all groups the current user is a member of."""
    db = get_db_client()
    all_groups = db.collection("groups").get()
    result = []
    for g in all_groups:
        data = g.to_dict()
        if user["id"] in data.get("member_ids", []):
            result.append(data)
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return result

@app.get("/groups/{group_id}")
def get_group(group_id: str, user: dict = Depends(require_user)):
    """Get group details including all member public keys for E2EE."""
    db = get_db_client()
    snap = db.collection("groups").document(group_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Group not found.")
    group_data = snap.to_dict()
    if user["id"] not in group_data.get("member_ids", []):
        raise HTTPException(status_code=403, detail="You are not a member of this group.")

    # Fetch all member profiles + public keys
    members = []
    for uid in group_data.get("member_ids", []):
        u_snap = db.collection("users").document(uid).get()
        if u_snap.exists:
            u = u_snap.to_dict()
            members.append({
                "id": u["id"],
                "username": u["username"],
                "display_name": u.get("display_name"),
                "avatar_index": u.get("avatar_index", 1),
                "public_key_jwk": u.get("public_key_jwk"),
            })
    return {**group_data, "members": members}

@app.post("/groups/{group_id}/members")
def add_group_member(group_id: str, payload: dict, user: dict = Depends(require_user)):
    """Add a new member to a group."""
    db = get_db_client()
    snap = db.collection("groups").document(group_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Group not found.")
    group_data = snap.to_dict()
    if group_data["creator_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the group creator can add members.")

    username = payload.get("username", "").strip()
    u_snaps = db.collection("users").where("username", "==", username).get()
    if not u_snaps:
        raise HTTPException(status_code=404, detail="User not found.")
    new_uid = u_snaps[0].to_dict()["id"]

    member_ids = group_data.get("member_ids", [])
    if new_uid in member_ids:
        return {"status": "already_member"}
    if len(member_ids) >= 50:
        raise HTTPException(status_code=400, detail="Group is full (max 50 members).")

    member_ids.append(new_uid)
    db.collection("groups").document(group_id).update({"member_ids": member_ids})
    return {"status": "added", "member_ids": member_ids}

@app.post("/groups/{group_id}/messages")
def send_group_message(group_id: str, payload: dict, user: dict = Depends(require_user)):
    """Send an E2EE message to a group."""
    db = get_db_client()
    snap = db.collection("groups").document(group_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Group not found.")
    group_data = snap.to_dict()
    if user["id"] not in group_data.get("member_ids", []):
        raise HTTPException(status_code=403, detail="You are not a member of this group.")

    msg_id = f"gmsg_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    # encrypted_keys is a dict: { user_id: encrypted_aes_key_for_that_user }
    msg_data = {
        "id": msg_id,
        "group_id": group_id,
        "sender_id": user["id"],
        "sender_username": user["username"],
        "encrypted_text": payload.get("encrypted_text", ""),
        "encrypted_keys": payload.get("encrypted_keys", {}),  # {uid: encrypted_key}
        "is_encrypted": True,
        "created_at": now,
    }
    db.collection("group_messages").document(msg_id).set(msg_data)
    return msg_data

@app.get("/groups/{group_id}/messages")
def get_group_messages(group_id: str, user: dict = Depends(require_user)):
    """Fetch all E2EE messages for a group."""
    db = get_db_client()
    snap = db.collection("groups").document(group_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Group not found.")
    group_data = snap.to_dict()
    if user["id"] not in group_data.get("member_ids", []):
        raise HTTPException(status_code=403, detail="You are not a member of this group.")

    all_msgs = db.collection("group_messages").get()
    result = []
    for m in all_msgs:
        data = m.to_dict()
        if data.get("group_id") == group_id:
            result.append(data)

    result.sort(key=lambda x: x.get("created_at", ""))
    return result



@app.get("/explore")
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

@app.get("/users")
def list_users():
    db = get_db_client()
    snaps = db.collection("users").get()
    return [s.to_dict() for s in snaps]


# --- 12. RESET SYSTEM STATE ---

@app.post("/reset")
def reset_system():
    # Clear local file directories
    for directory in [settings.TRUSTED_DOCS_DIR, settings.GENERATED_VIDEOS_DIR, settings.GENERATED_IMAGES_DIR]:
        if directory.exists():
            shutil.rmtree(directory)
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
