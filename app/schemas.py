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
    id: int
    title: str
    filename: str
    uploaded_at: datetime

    model_config = {"from_attributes": True}

class SocialPostResponse(BaseModel):
    id: int
    post_id: str
    source: str
    username: str
    content: str
    timestamp: str
    likes: int
    retweets: int
    confidence_score: float
    status: str
    matched_document_id: Optional[int] = None
    matched_snippet: Optional[str] = None
    video_path: Optional[str] = None
    image_path: Optional[str] = None
    likes_count: int
    user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- USER & PROFILE SCHEMAS ---

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=4)
    display_name: Optional[str] = None

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_index: int
    created_at: datetime

    model_config = {"from_attributes": True}

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_index: Optional[int] = None

class UserProfileResponse(BaseModel):
    id: int
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
    id: int
    user_id: int
    post_id: int
    text: str
    username: str
    avatar_index: int
    created_at: datetime

    model_config = {"from_attributes": True}


# --- DIRECT MESSAGE SCHEMAS ---

class MessageCreate(BaseModel):
    recipient_username: str
    text: str = Field(..., min_length=1)

class MessageResponse(BaseModel):
    id: int
    sender_id: int
    recipient_id: int
    text: str
    sender_username: str
    recipient_username: str
    created_at: datetime

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
