import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(100), nullable=False)
    display_name = Column(String(100), nullable=True)
    bio = Column(Text, nullable=True)
    avatar_index = Column(Integer, default=1)  # Local default avatar choice (1-8)
    reset_code = Column(String(10), nullable=True)
    reset_code_expires = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    # Relationships
    posts = relationship("SocialPost", back_populates="creator")
    comments = relationship("Comment", back_populates="user", cascade="all, delete-orphan")
    saved_posts = relationship("SavedPost", back_populates="user", cascade="all, delete-orphan")


class Follow(Base):
    __tablename__ = "follows"
    
    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    followed_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))


class Comment(Base):
    __tablename__ = "comments"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id = Column(Integer, ForeignKey("social_posts.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    # Relationships
    user = relationship("User", back_populates="comments")
    post = relationship("SocialPost", back_populates="comments")


class SavedPost(Base):
    __tablename__ = "saved_posts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id = Column(Integer, ForeignKey("social_posts.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    # Relationships
    user = relationship("User", back_populates="saved_posts")
    post = relationship("SocialPost", back_populates="saved_posts")


class DirectMessage(Base):
    __tablename__ = "direct_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))


class TrustedDocument(Base):
    __tablename__ = "trusted_documents"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    filename = Column(String(255), unique=True, index=True, nullable=False)
    content = Column(Text, nullable=False)
    uploaded_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    
    posts = relationship("SocialPost", back_populates="matched_document")


class SocialPost(Base):
    __tablename__ = "social_posts"
    
    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(String(100), unique=True, index=True, nullable=False)
    source = Column(String(50), nullable=False)  # "X", "Instagram", "System", etc.
    username = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(String(100), nullable=False)
    likes = Column(Integer, default=0)
    retweets = Column(Integer, default=0)
    
    # Verification stats
    confidence_score = Column(Float, default=0.0)
    status = Column(String(50), default="pending")  # "pending", "processing", "video_generation_pending", "human_review_required", "published", "rejected"
    
    # Link to trusted document matched
    matched_document_id = Column(Integer, ForeignKey("trusted_documents.id"), nullable=True)
    matched_snippet = Column(Text, nullable=True)
    
    # Generated Media Files
    video_path = Column(String(500), nullable=True)
    image_path = Column(String(500), nullable=True)
    likes_count = Column(Integer, default=0)
    
    # Link to creating user (if user upload)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

    # Relationships
    matched_document = relationship("TrustedDocument", back_populates="posts")
    creator = relationship("User", back_populates="posts")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")
    saved_posts = relationship("SavedPost", back_populates="post", cascade="all, delete-orphan")
