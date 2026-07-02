from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# --- EXISTING SCHEMAS (UPDATED) ---

class SocialPostMetadata(BaseModel):
    likes: int = Field(default=0)
    retweets: int = Field(default=0)

class SocialPostIngestPayload(BaseModel):
    source: str = Field(..., json_schema_extra={"example": "X"})
    post_id: str = Field(..., json_schema_extra={"example": "1234567890"})
    username: str = Field(..., json_schema_extra={"example": "news_agent_007"})
    content: str = Field(..., min_length=5, json_schema_extra={"example": "A massive solar flare..."})
    timestamp: str = Field(..., json_schema_extra={"example": "2026-06-18T20:00:00Z"})
    metadata: Optional[SocialPostMetadata] = None

class TrustedDocumentCreate(BaseModel):
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)

class TrustedDocumentResponse(BaseModel):
    id: str
    title: str
    filename: str
    uploaded_at: str

    model_config = {"from_attributes": True}

class SocialPostResponse(BaseModel):
    id: str
    post_id: str
    source: str
    username: str
    content: str
    timestamp: str
    likes: int
    retweets: int
    confidence_score: float
    accuracy_percentage: Optional[float] = None
    fact_check_report: Optional[str] = None
    status: str
    matched_document_id: Optional[str] = None
    matched_snippet: Optional[str] = None
    video_path: Optional[str] = None
    image_path: Optional[str] = None
    likes_count: int
    user_id: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


# --- USER & PROFILE SCHEMAS ---

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=4)
    display_name: Optional[str] = None

class UserLogin(BaseModel):
    username_or_email: Optional[str] = None
    username: Optional[str] = None
    password: str

class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_index: int
    created_at: str

    model_config = {"from_attributes": True}

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_index: Optional[int] = None

class UserProfileResponse(BaseModel):
    id: str
    username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_index: int
    posts_count: int
    followers_count: int
    following_count: int
    is_following: bool


# --- COMMENT SCHEMAS ---

class CommentCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)

class CommentResponse(BaseModel):
    id: str
    user_id: str
    post_id: str
    text: str
    username: str
    avatar_index: int
    created_at: str

    model_config = {"from_attributes": True}


# --- DIRECT MESSAGE SCHEMAS ---

class MessageCreate(BaseModel):
    recipient_username: str
    text: Optional[str] = None
    encrypted_text: Optional[str] = None
    encrypted_key_for_sender: Optional[str] = None
    encrypted_key_for_recipient: Optional[str] = None

class MessageResponse(BaseModel):
    id: str
    sender_id: str
    recipient_id: str
    text: Optional[str] = None
    encrypted_text: Optional[str] = None
    encrypted_key_for_sender: Optional[str] = None
    encrypted_key_for_recipient: Optional[str] = None
    is_encrypted: bool
    sender_username: str
    recipient_username: str
    created_at: str

    model_config = {"from_attributes": True}


# --- GOOGLE AUTH SCHEMAS ---

class UserGoogleLogin(BaseModel):
    email: str = Field(..., min_length=5)
    display_name: Optional[str] = None


# --- PASSWORD RESET SCHEMAS ---

class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=5)

class ResetPasswordRequest(BaseModel):
    email: str = Field(..., min_length=5)
    reset_code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=4)
