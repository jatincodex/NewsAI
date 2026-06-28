import os
import uuid
import random
import shutil
from typing import List, Optional
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, status, Header
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.config import settings
from app.database import Base, engine, get_db
from app.auth import AuthHandler
from app.models import SocialPost, TrustedDocument, User, Follow, Comment, SavedPost, DirectMessage
from app.schemas import (
    SocialPostIngestPayload,
    SocialPostResponse,
    TrustedDocumentCreate,
    TrustedDocumentResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
    UserProfileResponse,
    CommentCreate,
    CommentResponse,
    MessageCreate,
    MessageResponse,
    UserGoogleLogin,
    ForgotPasswordRequest,
    ResetPasswordRequest
)
from app.tasks import process_social_post, generate_video_task

# Create SQL tables automatically on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Instagram-style news container platform with verification and reels synthesis."
)

# Mount static folder for assets
app.mount("/static", StaticFiles(directory=str(settings.BASE_DIR / "static")), name="static")

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# --- AUTHENTICATION DEPENDENCIES ---

def get_current_user(db: Session = Depends(get_db), authorization: Optional[str] = Header(None)) -> Optional[User]:
    """Dependency to retrieve the currently logged in user context."""
    if not authorization:
        return None
    token = authorization
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    user_id = AuthHandler.verify_token(token)
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()

def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    """Dependency that raises 401 if user is not authenticated."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required."
        )
    return user


# --- STATIC ASSETS ---

@app.get("/", response_class=HTMLResponse)
def read_root():
    """Serves the News AI Platform (Instagram Clone interface)."""
    index_path = settings.BASE_DIR / "static" / "index.html"
    if not index_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard frontend assets missing."
        )
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


# --- AUTHENTICATION APIS ---

@app.post("/auth/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, db: Session = Depends(get_db)):
    # Enforce Gmail address constraint
    email_clean = payload.email.strip().lower()
    if not email_clean.endswith("@gmail.com"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration is restricted to valid Gmail accounts (@gmail.com) only."
        )

    # Check duplicate username
    existing_user = db.query(User).filter(User.username == payload.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken."
        )
    # Check duplicate email
    existing_email = db.query(User).filter(User.email == email_clean).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered."
        )
        
    hashed = AuthHandler.hash_password(payload.password)
    user = User(
        username=payload.username,
        email=email_clean,
        hashed_password=hashed,
        display_name=payload.display_name or payload.username,
        avatar_index=os.urandom(1)[0] % 8 + 1  # Pick a random avatar between 1 and 8
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    token = AuthHandler.generate_token(user.id, user.username)
    return {"token": token, "user": UserResponse.model_validate(user)}

@app.post("/auth/login")
def login(payload: UserLogin, db: Session = Depends(get_db)):
    credential = payload.username.strip().lower()
    user = db.query(User).filter(
        or_(
            User.username == credential,
            User.email == credential
        )
    ).first()
    if not user or not AuthHandler.verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/email or password."
        )
    token = AuthHandler.generate_token(user.id, user.username)
    return {"token": token, "user": UserResponse.model_validate(user)}

@app.post("/auth/google")
def google_auth(payload: UserGoogleLogin, db: Session = Depends(get_db)):
    """Mock Google Sign-In endpoint that logs in or registers users using their verified Gmail address."""
    email_clean = payload.email.strip().lower()
    if not email_clean.endswith("@gmail.com"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Sign-In is restricted to valid Gmail accounts (@gmail.com) only."
        )
        
    # Check if user already registered with this Gmail
    user = db.query(User).filter(User.email == email_clean).first()
    
    if not user:
        # Automatically register a new user for this Gmail account
        prefix = email_clean.split("@")[0]
        safe_username = "".join([c if c.isalnum() else "_" for c in prefix]).strip("_")
        
        # Make sure username is unique
        existing_username = db.query(User).filter(User.username == safe_username).first()
        if existing_username:
            safe_username = f"{safe_username}_{uuid.uuid4().hex[:4]}"
            
        random_password = uuid.uuid4().hex
        hashed = AuthHandler.hash_password(random_password)
        
        user = User(
            username=safe_username,
            email=email_clean,
            hashed_password=hashed,
            display_name=payload.display_name or safe_username,
            avatar_index=os.urandom(1)[0] % 8 + 1
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
    token = AuthHandler.generate_token(user.id, user.username)
    return {"token": token, "user": UserResponse.model_validate(user)}

@app.post("/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    email_clean = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email_clean).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email address not found."
        )
    
    # Generate 6-digit reset code
    code = f"{random.randint(100000, 999999)}"
    user.reset_code = code
    # Set expiration to 15 minutes
    from datetime import timedelta
    user.reset_code_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    db.commit()
    
    # Print reset code to terminal for easy retrieval during local testing
    print(f"\n=====================================")
    print(f"PASSWORD RESET REQUEST")
    print(f"Email: {email_clean}")
    print(f"Reset Code: {code}")
    print(f"=====================================\n")
    
    return {"message": "Reset code successfully generated.", "reset_code": code}

@app.post("/auth/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    email_clean = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email_clean).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email address not found."
        )
        
    if not user.reset_code or user.reset_code != payload.reset_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid password reset code."
        )
        
    expires = user.reset_code_expires
    if expires:
        now_val = datetime.now(timezone.utc) if expires.tzinfo else datetime.now(timezone.utc).replace(tzinfo=None)
        if now_val > expires:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password reset code has expired."
            )
            
    # Reset password
    hashed = AuthHandler.hash_password(payload.new_password)
    user.hashed_password = hashed
    user.reset_code = None
    user.reset_code_expires = None
    db.commit()
    
    return {"message": "Password reset successfully."}

@app.get("/auth/me", response_model=UserResponse)
def get_me(user: User = Depends(require_user)):
    return user

@app.post("/auth/update", response_model=UserResponse)
def update_profile(payload: UserUpdate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if payload.bio is not None:
        user.bio = payload.bio.strip()
    if payload.avatar_index is not None:
        if 1 <= payload.avatar_index <= 8:
            user.avatar_index = payload.avatar_index
            
    db.commit()
    db.refresh(user)
    return user


# --- SOCIAL FEED & INGESTION APIS ---

@app.post("/ingest", response_model=SocialPostResponse, status_code=status.HTTP_201_CREATED)
def ingest_social_post(payload: SocialPostIngestPayload, db: Session = Depends(get_db), current_user: Optional[User] = Depends(get_current_user)):
    """
    Ingest a new social media post payload.
    Saves the post to the database, then triggers the Celery worker task.
    """
    existing_post = db.query(SocialPost).filter(SocialPost.post_id == payload.post_id).first()
    if existing_post:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Post with ID '{payload.post_id}' has already been ingested."
        )
        
    likes_count = payload.metadata.likes if payload.metadata else 0
    retweets = payload.metadata.retweets if payload.metadata else 0
    
    post = SocialPost(
        post_id=payload.post_id,
        source=payload.source,
        username=payload.username,
        content=payload.content,
        timestamp=payload.timestamp,
        likes=likes_count,
        retweets=retweets,
        likes_count=likes_count,
        status="pending",
        user_id=current_user.id if current_user else None
    )
    
    db.add(post)
    db.commit()
    db.refresh(post)
    
    process_social_post.delay(post.id)
    return post

@app.post("/posts/create", response_model=SocialPostResponse, status_code=status.HTTP_201_CREATED)
def create_custom_post(content: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Enables logged-in users to write custom posts, passing them through verification logic."""
    post_id = f"custom_{uuid.uuid4().hex[:8]}"
    post = SocialPost(
        post_id=post_id,
        source="NewsAI",
        username=user.username,
        content=content,
        timestamp=datetime.now(timezone.utc).isoformat(),
        likes=0,
        retweets=0,
        likes_count=0,
        status="pending",
        user_id=user.id
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    
    process_social_post.delay(post.id)
    return post

@app.get("/posts", response_model=List[SocialPostResponse])
def get_posts(status_filter: Optional[str] = None, db: Session = Depends(get_db)):
    """Fetch all ingested social media posts (excluding rejected items)."""
    q = db.query(SocialPost).filter(SocialPost.status != "rejected")
    if status_filter:
        q = q.filter(SocialPost.status == status_filter)
    return q.order_by(SocialPost.created_at.desc()).all()

@app.get("/posts/saved", response_model=List[SocialPostResponse])
def get_saved_posts(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Retrieve bookmarked posts for the current authenticated user."""
    saves = db.query(SavedPost).filter(SavedPost.user_id == user.id).all()
    post_ids = [s.post_id for s in saves]
    return db.query(SocialPost).filter(SocialPost.id.in_(post_ids)).order_by(SocialPost.created_at.desc()).all()

@app.get("/posts/{post_id}", response_model=SocialPostResponse)
def get_post_by_id(post_id: str, db: Session = Depends(get_db)):
    """Retrieve details for a single social media post."""
    post = db.query(SocialPost).filter(SocialPost.post_id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post with ID '{post_id}' not found."
        )
    return post

@app.post("/posts/{post_id}/like")
def like_post(post_id: str, action: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    post = db.query(SocialPost).filter(SocialPost.post_id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found."
        )
    if action == "like":
        post.likes_count += 1
    elif action == "unlike" and post.likes_count > 0:
        post.likes_count -= 1
        
    db.commit()
    return {"likes_count": post.likes_count}


# --- MEDIA SERVING APIS ---

@app.get("/posts/{post_id}/video")
def serve_post_video(post_id: str, db: Session = Depends(get_db)):
    """Streams the vertical synthesized MP4 video file associated with a post."""
    post = db.query(SocialPost).filter(SocialPost.post_id == post_id).first()
    if not post or not post.video_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video for post ID '{post_id}' not found or generation not finished."
        )
        
    video_file = Path(post.video_path)
    if not video_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video file is missing from local storage."
        )
        
    return FileResponse(str(video_file), media_type="video/mp4", filename=video_file.name)

@app.get("/posts/{post_id}/image")
def serve_post_image(post_id: str, db: Session = Depends(get_db)):
    """Serves the generated square PNG image associated with a post."""
    post = db.query(SocialPost).filter(SocialPost.post_id == post_id).first()
    if not post or not post.image_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image for post ID '{post_id}' not found."
        )
        
    image_file = Path(post.image_path)
    if not image_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image card file is missing from local storage."
        )
        
    return FileResponse(str(image_file), media_type="image/png")


# --- TRUSTED DOCUMENTS ARCHIVE ---

@app.post("/trusted-docs", response_model=TrustedDocumentResponse, status_code=status.HTTP_201_CREATED)
def create_trusted_document(payload: TrustedDocumentCreate, db: Session = Depends(get_db)):
    """Registers a trusted reference fact-checking document."""
    existing_doc = db.query(TrustedDocument).filter(TrustedDocument.title == payload.title).first()
    if existing_doc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trusted document with title '{payload.title}' already registered."
        )
        
    safe_title = "".join([c if c.isalnum() else "_" for c in payload.title]).strip("_")
    filename = f"{safe_title}_{uuid.uuid4().hex[:6]}.txt"
    
    settings.TRUSTED_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = settings.TRUSTED_DOCS_DIR / filename
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(payload.content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write trusted document to local filesystem: {str(e)}"
        )
        
    db_doc = TrustedDocument(
        title=payload.title,
        filename=filename,
        content=payload.content
    )
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)
    
    return db_doc

@app.get("/trusted-docs", response_model=List[TrustedDocumentResponse])
def list_trusted_documents(db: Session = Depends(get_db)):
    """Retrieve list of all trusted documents."""
    return db.query(TrustedDocument).all()


# --- MANUAL REVIEW DECISION WORKSPACE ---

@app.post("/posts/{post_id}/approve", response_model=SocialPostResponse)
def approve_post(post_id: str, db: Session = Depends(get_db)):
    """Manually approve a flagged post, overriding the safety gate and launching video synthesis."""
    post = db.query(SocialPost).filter(SocialPost.post_id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post with ID '{post_id}' not found."
        )
        
    if post.status != "human_review_required":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only posts requiring review can be approved. Current status: '{post.status}'."
        )
        
    post.status = "video_generation_pending"
    db.commit()
    
    # Launch video generation task
    generate_video_task.delay(post.id)
    
    # Refresh to load updates made by the Celery task (such as transitioning status to published and setting video_path)
    db.refresh(post)
    return post

@app.post("/posts/{post_id}/reject", response_model=SocialPostResponse)
def reject_post(post_id: str, db: Session = Depends(get_db)):
    """Manually reject/discard a flagged post, preventing video synthesis."""
    post = db.query(SocialPost).filter(SocialPost.post_id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post with ID '{post_id}' not found."
        )
        
    if post.status != "human_review_required":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only posts requiring review can be rejected. Current status: '{post.status}'."
        )
        
    post.status = "rejected"
    db.commit()
    return post


# --- SOCIAL USER INTERACTIONS APIS ---

@app.post("/users/{username}/follow")
def follow_user(username: str, db: Session = Depends(get_db), current_user: User = Depends(require_user)):
    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found.")
    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot follow yourself.")
        
    follow_relation = db.query(Follow).filter(
        Follow.follower_id == current_user.id,
        Follow.followed_id == target_user.id
    ).first()
    
    if follow_relation:
        db.delete(follow_relation)
        db.commit()
        return {"status": "unfollowed"}
    else:
        new_follow = Follow(follower_id=current_user.id, followed_id=target_user.id)
        db.add(new_follow)
        db.commit()
        return {"status": "followed"}

@app.get("/users/{username}/profile", response_model=UserProfileResponse)
def get_user_profile(username: str, db: Session = Depends(get_db), current_user: Optional[User] = Depends(get_current_user)):
    target_user = db.query(User).filter(User.username == username).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")
        
    posts_count = db.query(SocialPost).filter(SocialPost.username == username, SocialPost.status != "rejected").count()
    followers_count = db.query(Follow).filter(Follow.followed_id == target_user.id).count()
    following_count = db.query(Follow).filter(Follow.follower_id == target_user.id).count()
    
    is_following = False
    if current_user:
        is_following = db.query(Follow).filter(
            Follow.follower_id == current_user.id,
            Follow.followed_id == target_user.id
        ).count() > 0
        
    return UserProfileResponse(
        id=target_user.id,
        username=target_user.username,
        display_name=target_user.display_name,
        bio=target_user.bio,
        avatar_index=target_user.avatar_index,
        posts_count=posts_count,
        followers_count=followers_count,
        following_count=following_count,
        is_following=is_following
    )


# --- COMMENTS APIS ---

@app.get("/posts/{post_id}/comments", response_model=List[CommentResponse])
def get_comments(post_id: str, db: Session = Depends(get_db)):
    post = db.query(SocialPost).filter(SocialPost.post_id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
        
    comments = db.query(Comment).filter(Comment.post_id == post.id).order_by(Comment.created_at.asc()).all()
    
    res = []
    for c in comments:
        res.append(CommentResponse(
            id=c.id,
            user_id=c.user_id,
            post_id=c.post_id,
            text=c.text,
            username=c.user.username,
            avatar_index=c.user.avatar_index,
            created_at=c.created_at
        ))
    return res

@app.post("/posts/{post_id}/comments", response_model=CommentResponse)
def add_comment(post_id: str, payload: CommentCreate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    post = db.query(SocialPost).filter(SocialPost.post_id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
        
    comment = Comment(
        user_id=user.id,
        post_id=post.id,
        text=payload.text
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    
    return CommentResponse(
        id=comment.id,
        user_id=comment.user_id,
        post_id=comment.post_id,
        text=comment.text,
        username=user.username,
        avatar_index=user.avatar_index,
        created_at=comment.created_at
    )


# --- BOOKMARKS (SAVED POSTS) APIS ---

@app.post("/posts/{post_id}/save")
def save_post(post_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    post = db.query(SocialPost).filter(SocialPost.post_id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
        
    existing = db.query(SavedPost).filter(SavedPost.user_id == user.id, SavedPost.post_id == post.id).first()
    if existing:
        return {"status": "already_saved"}
        
    saved = SavedPost(user_id=user.id, post_id=post.id)
    db.add(saved)
    db.commit()
    return {"status": "saved"}

@app.delete("/posts/{post_id}/save")
def unsave_post(post_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    post = db.query(SocialPost).filter(SocialPost.post_id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
        
    saved = db.query(SavedPost).filter(SavedPost.user_id == user.id, SavedPost.post_id == post.id).first()
    if saved:
        db.delete(saved)
        db.commit()
    return {"status": "unsaved"}



# --- DIRECT MESSAGES (DMs) APIS ---

@app.post("/messages", response_model=MessageResponse)
def send_message(payload: MessageCreate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    recipient = db.query(User).filter(User.username == payload.recipient_username).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient user not found.")
    if recipient.id == user.id:
        raise HTTPException(status_code=400, detail="You cannot message yourself.")
        
    msg = DirectMessage(
        sender_id=user.id,
        recipient_id=recipient.id,
        text=payload.text
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    
    return MessageResponse(
        id=msg.id,
        sender_id=msg.sender_id,
        recipient_id=msg.recipient_id,
        text=msg.text,
        sender_username=user.username,
        recipient_username=recipient.username,
        created_at=msg.created_at
    )

@app.get("/messages", response_model=List[MessageResponse])
def get_messages(with_user: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    other_user = db.query(User).filter(User.username == with_user).first()
    if not other_user:
        raise HTTPException(status_code=404, detail="User not found.")
        
    # Get chat history between user and other_user
    msgs = db.query(DirectMessage).filter(
        or_(
            (DirectMessage.sender_id == user.id) & (DirectMessage.recipient_id == other_user.id),
            (DirectMessage.sender_id == other_user.id) & (DirectMessage.recipient_id == user.id)
        )
    ).order_by(DirectMessage.created_at.asc()).all()
    
    res = []
    for m in msgs:
        res.append(MessageResponse(
            id=m.id,
            sender_id=m.sender_id,
            recipient_id=m.recipient_id,
            text=m.text,
            sender_username=user.username if m.sender_id == user.id else other_user.username,
            recipient_username=other_user.username if m.sender_id == user.id else user.username,
            created_at=m.created_at
        ))
    return res

@app.get("/explore", response_model=List[SocialPostResponse])
def explore_posts(query: Optional[str] = None, db: Session = Depends(get_db)):
    """Explore and search posts by content term."""
    q = db.query(SocialPost).filter(SocialPost.status != "rejected")
    if query:
        q = q.filter(SocialPost.content.like(f"%{query}%"))
    return q.order_by(SocialPost.created_at.desc()).all()


# --- RESET SYSTEM STATE ---

@app.get("/users", response_model=List[UserResponse])
def list_users(db: Session = Depends(get_db)):
    """Retrieve list of all registered users."""
    return db.query(User).all()

@app.post("/reset")
def reset_system(db: Session = Depends(get_db)):
    """Utility endpoint to flush the database, user tables, and local file storage directories."""
    # Delete database records
    db.query(SocialPost).delete()
    db.query(TrustedDocument).delete()
    db.query(User).delete()
    db.query(Follow).delete()
    db.query(Comment).delete()
    db.query(SavedPost).delete()
    db.query(DirectMessage).delete()
    db.commit()
    
    # Clear local file directories
    for directory in [settings.TRUSTED_DOCS_DIR, settings.GENERATED_VIDEOS_DIR, settings.GENERATED_IMAGES_DIR]:
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
        
    return {"message": "System database, trusted files, static post images, and generated videos reset successfully."}
