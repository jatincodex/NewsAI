import os
import time
import uuid
import random
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import Header, Depends, HTTPException, status
from app.core.config import settings

logger = logging.getLogger(__name__)

class AuthHandler:
    # Industry standard recommendation: avoid hardcoded secrets in source files.
    # Fallback is provided, but in production, this should be set in environment.
    SECRET_KEY = os.getenv("NEWS_AI_JWT_SECRET", "news_ai_super_secure_salt_999")

    @classmethod
    def hash_password(cls, password: str) -> str:
        """Hashes the password using PBKDF2-SHA256 with 100,000 iterations."""
        return hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            cls.SECRET_KEY.encode('utf-8'),
            100000
        ).hex()

    @classmethod
    def verify_password(cls, plain_password: str, hashed_password: str) -> bool:
        """Verifies if the plain password matches the hashed password."""
        return cls.hash_password(plain_password) == hashed_password
        
    @classmethod
    def generate_token(cls, user_id: str, username: str) -> str:
        """Generates a simple, signed session token."""
        payload = f"{user_id}:{username}"
        signature = hashlib.sha256((payload + cls.SECRET_KEY).encode('utf-8')).hexdigest()[:16]
        return f"{payload}:{signature}"

    @classmethod
    def verify_token(cls, token: Optional[str]) -> Optional[str]:
        """
        Verifies a session token and returns the user_id if valid.
        Returns None if invalid or missing.
        """
        if not token:
            return None
        try:
            parts = token.split(":")
            if len(parts) != 3:
                return None
            user_id_str, username, signature = parts
            payload = f"{user_id_str}:{username}"
            expected_signature = hashlib.sha256((payload + cls.SECRET_KEY).encode('utf-8')).hexdigest()[:16]
            if signature == expected_signature:
                return user_id_str
        except Exception:
            pass
        return None


# Import firebase db client and verify token function dynamically to avoid circular dependencies
def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """Dependency to retrieve the currently logged in user context via Firebase ID tokens."""
    if not authorization:
        return None
        
    token = authorization
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        
    from app.core.firebase_config import verify_token, get_db_client
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
