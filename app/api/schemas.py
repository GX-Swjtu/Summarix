from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.config import ThinkingMode

ArtifactSource = Literal["screenshot", "page_text", "selection", "upload"]


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    created_at: datetime


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "user@example.com", "password": "StrongPass123"}}
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "user@example.com", "password": "StrongPass123"}}
    )


class AuthResponse(BaseModel):
    user: UserPublic


class ConversationContext(BaseModel):
    page_url: str | None = None
    page_title: str | None = None
    page_text: str | None = None


class ChatStreamRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=20000)
    context: ConversationContext | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    suggested_questions: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "conversation_id": None,
                "message": "请总结当前网页，并结合截图指出重点信息。",
                "context": {
                    "page_url": "https://example.com/article",
                    "page_title": "Example Article",
                    "page_text": "网页正文内容...",
                },
                "artifact_ids": ["8e34a2c2-6e9e-4e90-9f92-6e1bc0f3b8b2"],
                "suggested_questions": True,
            }
        }
    )


class SuggestedQuestionsStreamRequest(BaseModel):
    conversation_id: str
    assistant_message_id: str | None = None
    count: int = Field(default=3, ge=1, le=5)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "conversation_id": "1fba6184-8e9a-4a3d-a6e1-cb7f65a6b4b1",
                "assistant_message_id": "62cdb617-711b-4db2-a813-855d2b9e0112",
                "count": 3,
            }
        }
    )


class ArtifactResponse(BaseModel):
    id: str
    filename: str
    mime_type: str
    size_bytes: int
    version: int
    source: str = "screenshot"
    page_url: str | None = None
    page_title: str | None = None
    text_excerpt: str | None = None
    text_length: int | None = None
    content_hash: str | None = None
    adk_invocation_id: str | None = None


class MessagePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: Literal["user", "assistant"] | str
    content: str
    adk_invocation_id: str | None = None
    created_at: datetime
    artifacts: list[ArtifactResponse] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    page_url: str | None
    page_title: str | None
    updated_at: datetime


class HistoryPage(BaseModel):
    items: list[ConversationSummary]
    limit: int
    offset: int
    has_more: bool


class ConversationDetail(ConversationSummary):
    messages: list[MessagePublic]
    artifacts: list[ArtifactResponse]


class ModelSettingsRequest(BaseModel):
    text_summary_model: str | None = Field(default=None, max_length=120)
    conversation_model: str | None = Field(default=None, max_length=120)
    xiaohongshu_model: str | None = Field(default=None, max_length=120)
    short_video_script_model: str | None = Field(default=None, max_length=120)
    suggested_questions_model: str | None = Field(default=None, max_length=120)
    text_summary_thinking_mode: ThinkingMode = "default"
    conversation_thinking_mode: ThinkingMode = "default"
    xiaohongshu_thinking_mode: ThinkingMode = "default"
    short_video_script_thinking_mode: ThinkingMode = "default"
    suggested_questions_thinking_mode: ThinkingMode = "disabled"

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text_summary_model": "dashscope/qwen3.5-flash",
                "conversation_model": "dashscope/qwen3.5-flash",
                "xiaohongshu_model": "dashscope/qwen3.5-flash",
                "short_video_script_model": "dashscope/qwen3.5-flash",
                "suggested_questions_model": "dashscope/qwen3.5-flash",
                "text_summary_thinking_mode": "default",
                "conversation_thinking_mode": "default",
                "xiaohongshu_thinking_mode": "default",
                "short_video_script_thinking_mode": "default",
                "suggested_questions_thinking_mode": "disabled",
            }
        }
    )


class ModelSettingsResponse(ModelSettingsRequest):
    defaults: dict[str, str]


class ErrorResponse(BaseModel):
    detail: str
