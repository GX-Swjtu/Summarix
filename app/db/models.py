from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    conversations: Mapped[list[Conversation]] = relationship(back_populates="user", cascade="all, delete-orphan")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user", cascade="all, delete-orphan")
    model_preference: Mapped[UserModelPreference | None] = relationship(back_populates="user", cascade="all, delete-orphan")
    message_feedback: Mapped[list[MessageFeedback]] = relationship(back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    adk_session_id: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False, default=new_uuid)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新会话")
    page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")
    artifacts: Mapped[list[MessageArtifact]] = relationship(back_populates="conversation")
    feedback_items: Mapped[list[MessageFeedback]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    adk_invocation_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    artifacts: Mapped[list[MessageArtifact]] = relationship(back_populates="message")
    feedback_items: Mapped[list[MessageFeedback]] = relationship(back_populates="message", cascade="all, delete-orphan")


class MessageArtifact(Base):
    __tablename__ = "message_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), index=True, nullable=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), index=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_filename: Mapped[str] = mapped_column(String(320), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="screenshot")
    page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    adk_invocation_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    conversation: Mapped[Conversation | None] = relationship(back_populates="artifacts")
    message: Mapped[Message | None] = relationship(back_populates="artifacts")


class UserModelPreference(Base):
    __tablename__ = "user_model_preferences"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_model_preferences_user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    primary_model_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    primary_thinking_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="default")
    text_summary_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    conversation_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    xiaohongshu_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    short_video_script_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    suggested_questions_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    text_summary_thinking_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="default")
    conversation_thinking_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="default")
    xiaohongshu_thinking_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="default")
    short_video_script_thinking_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="default")
    suggested_questions_thinking_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="disabled")
    theme: Mapped[str] = mapped_column(String(20), nullable=False, default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    user: Mapped[User] = relationship(back_populates="model_preference")


class MessageFeedback(Base):
    __tablename__ = "message_feedback"
    __table_args__ = (UniqueConstraint("user_id", "message_id", name="uq_message_feedback_user_message"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    adk_invocation_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="extension")
    langwatch_annotation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    langwatch_sync_status: Mapped[str] = mapped_column(String(30), nullable=False, default="disabled")
    langwatch_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    user: Mapped[User] = relationship(back_populates="message_feedback")
    conversation: Mapped[Conversation] = relationship(back_populates="feedback_items")
    message: Mapped[Message] = relationship(back_populates="feedback_items")
