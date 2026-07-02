import time
import uuid
import random
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import AuthHandler, require_user
from app.core.firebase_config import get_db_client
from app.models.schemas import UserCreate, UserLogin, UserGoogleLogin, ForgotPasswordRequest, ResetPasswordRequest, UserUpdate, UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(payload: UserCreate):
    username = payload.username.strip()
    email = payload.email.strip()
    password = payload.password
    display_name = payload.display_name.strip() if payload.display_name else ""

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

@router.post("/login")
async def login(payload: UserLogin):
    user_or_email = (payload.username_or_email or payload.username or "").strip()
    password = payload.password

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

@router.post("/google")
async def google_login(payload: UserGoogleLogin):
    email = payload.email.strip()
    display_name = payload.display_name.strip() if payload.display_name else ""

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

@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest):
    email = payload.email.strip()
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

@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest):
    email = payload.email.strip()
    code = payload.reset_code.strip()
    new_password = payload.new_password

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

@router.get("/me")
def get_me(user: dict = Depends(require_user)):
    return user

@router.post("/update")
def update_profile(payload: UserUpdate, user: dict = Depends(require_user)):
    db = get_db_client()
    user_ref = db.collection("users").document(user["id"])
    
    updates = {}
    if payload.display_name is not None:
        updates["display_name"] = payload.display_name.strip()
    if payload.bio is not None:
        updates["bio"] = payload.bio.strip()
    if payload.avatar_index is not None:
        avatar = int(payload.avatar_index)
        if 1 <= avatar <= 8:
            updates["avatar_index"] = avatar
            
    if updates:
        user_ref.update(updates)
        user.update(updates)
        
    return user
