import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


LOCAL_EXTENSION_ORIGIN_REGEX = r"^(chrome-extension://[a-p]{32}|moz-extension://[0-9a-fA-F-]{36})$"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Summarix"
    app_env: str = "local"
    api_prefix: str = "/api"
    host: str = "127.0.0.1"
    port: int = 8000

    database_url: str = Field(..., min_length=1)
    database_auto_create_database: bool = True
    database_auto_create_tables: bool = True

    jwt_secret_key: str = "change-me-in-.env"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    access_cookie_name: str = "summarix_access"
    refresh_cookie_name: str = "summarix_refresh"
    refresh_cookie_path: str | None = None
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_cookie_domain: str | None = None

    cors_allow_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    browser_extension_origins: list[str] = Field(default_factory=list)
    cors_allow_origin_regex: str | None = None

    chat_app_name: str = "summarix"
    chat_agent_mode: Literal["adk", "mock"] = "adk"
    chat_artifact_root: str = ".data/artifacts"
    chat_max_artifact_bytes: int = 8 * 1024 * 1024
    default_chat_model: str = "dashscope/qwen3.5-flash"
    text_summary_model: str | None = None
    conversation_model: str | None = None
    xiaohongshu_model: str | None = None
    short_video_script_model: str | None = None
    adk_database_url: str | None = None

    @field_validator("cors_allow_origins", "browser_extension_origins", mode="before")
    @classmethod
    def parse_cors_origin_list(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_allow_origin_regex")
    @classmethod
    def validate_cors_allow_origin_regex(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            pattern = re.compile(value)
        except re.error as exc:
            raise ValueError("CORS_ALLOW_ORIGIN_REGEX 不是合法正则表达式") from exc
        extension_origins = (
            "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
            "moz-extension://12345678-1234-1234-1234-123456789abc",
        )
        if any(pattern.fullmatch(origin) for origin in extension_origins):
            raise ValueError("请使用 BROWSER_EXTENSION_ORIGINS 配置明确的浏览器插件来源")
        return value

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        weak_secrets = {"", "change-me-in-.env", "please-change-this-secret"}
        if self.jwt_secret_key in weak_secrets or len(self.jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY 必须设置为至少 32 个字符的强随机密钥")
        return self

    @property
    def artifact_root_path(self) -> Path:
        return Path(self.chat_artifact_root).resolve()

    @property
    def effective_refresh_cookie_path(self) -> str:
        if self.refresh_cookie_path:
            return self.refresh_cookie_path
        api_prefix = self.api_prefix.rstrip("/")
        return f"{api_prefix}/auth" if api_prefix else "/auth"

    @property
    def effective_cors_allow_origins(self) -> list[str]:
        return list(dict.fromkeys([*self.cors_allow_origins, *self.browser_extension_origins]))

    @property
    def effective_cors_allow_origin_regex(self) -> str | None:
        if self.cors_allow_origin_regex:
            return self.cors_allow_origin_regex
        if self.browser_extension_origins:
            return None
        if self.app_env.lower() not in {"local", "development", "dev"}:
            return None
        return LOCAL_EXTENSION_ORIGIN_REGEX

    @property
    def effective_adk_database_url(self) -> str:
        return self.adk_database_url or self.database_url

    @property
    def effective_text_model(self) -> str:
        return self.text_summary_model or self.default_chat_model

    @property
    def effective_conversation_model(self) -> str:
        return self.conversation_model or self.default_chat_model

    @property
    def effective_xiaohongshu_model(self) -> str:
        return self.xiaohongshu_model or self.default_chat_model

    @property
    def effective_short_video_script_model(self) -> str:
        return self.short_video_script_model or self.default_chat_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
