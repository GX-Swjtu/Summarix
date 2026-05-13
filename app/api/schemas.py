from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text_summary_model": "dashscope/qwen3.5-flash",
                "conversation_model": "dashscope/qwen3.5-flash",
                "xiaohongshu_model": "dashscope/qwen3.5-flash",
                "short_video_script_model": "dashscope/qwen3.5-flash",
            }
        }
    )


class ModelSettingsResponse(ModelSettingsRequest):
    defaults: dict[str, str]


class ErrorResponse(BaseModel):
    detail: str
