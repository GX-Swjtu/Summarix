import json
import re
from functools import cached_property
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


LOCAL_EXTENSION_ORIGIN_REGEX = r"^(chrome-extension://[a-p]{32}|moz-extension://[0-9a-fA-F-]{36})$"
ThinkingMode = Literal["default", "enabled", "disabled"]
LogFormat = Literal["text", "json"]
LangWatchOutputGuardrailMode = Literal["audit", "block"]


@dataclass(frozen=True)
class ChatModelDefinition:
    id: str
    name: str
    description: str
    is_premium: bool
    icon_url: str | None
    api_base: str | None
    api_key: str | None
    litellm_model: str
    supports_thinking_config: bool
    default_thinking_mode: ThinkingMode = "default"


def normalize_thinking_mode(value: str | None, fallback: ThinkingMode = "default") -> ThinkingMode:
    if value in {"default", "enabled", "disabled"}:
        return value
    return fallback


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Summarix"
    app_env: str = "local"
    app_reload: bool | None = None
    api_prefix: str = "/api"
    host: str = "127.0.0.1"
    port: int = 8000
    log_format: LogFormat = "text"
    log_level: str = "INFO"
    trace_id_header: str = "X-Trace-ID"

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

    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    browser_extension_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    cors_allow_origin_regex: str | None = None

    chat_app_name: str = "summarix"
    chat_agent_mode: Literal["adk", "mock"] = "adk"
    chat_artifact_root: str = ".data/artifacts"
    chat_max_artifact_bytes: int = 8 * 1024 * 1024
    model_asset_root: str = "iconResources"
    default_chat_model: str = "dashscope/qwen3.5-flash"
    model_catalog_file: str | None = None
    model_catalog_json: str | None = None
    default_primary_model_id: str | None = None
    suggested_questions_model_id: str | None = None
    text_summary_model: str | None = None
    conversation_model: str | None = None
    xiaohongshu_model: str | None = None
    short_video_script_model: str | None = None
    suggested_questions_model: str | None = None
    text_summary_thinking_mode: ThinkingMode = "default"
    conversation_thinking_mode: ThinkingMode = "default"
    xiaohongshu_thinking_mode: ThinkingMode = "default"
    short_video_script_thinking_mode: ThinkingMode = "default"
    suggested_questions_thinking_mode: ThinkingMode = "disabled"
    adk_database_url: str | None = None

    prometheus_enabled: bool = False
    prometheus_metrics_path: str = "/metrics"

    langwatch_enabled: bool = False
    langwatch_api_key: str | None = None
    langwatch_endpoint: str | None = None
    langwatch_public_url: str | None = None
    langwatch_debug: bool = False
    langwatch_guardrails_enabled: bool = False
    langwatch_guardrails_fail_open: bool = True
    langwatch_input_guardrail_slug: str | None = None
    langwatch_output_guardrail_mode: LangWatchOutputGuardrailMode = "audit"
    langwatch_prompts_enabled: bool = False
    langwatch_chat_prompt_handle: str | None = None

    @field_validator("cors_allow_origins", "browser_extension_origins", mode="before")
    @classmethod
    def parse_cors_origin_list(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []

            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                if not inner:
                    return []

                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    return [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]

                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]

            return [item.strip().strip('"').strip("'") for item in value.split(",") if item.strip()]
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

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        weak_secrets = {"", "change-me-in-.env", "please-change-this-secret"}
        if self.jwt_secret_key in weak_secrets or len(self.jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY 必须设置为至少 32 个字符的强随机密钥")
        _ = self.effective_primary_model_definition
        _ = self.effective_suggested_questions_model_definition
        return self

    @staticmethod
    def _read_catalog_string(raw: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = raw.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    @staticmethod
    def _read_catalog_bool(raw: dict[str, Any], default: bool, *keys: str) -> bool:
        for key in keys:
            if key not in raw:
                continue
            value = raw[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            normalized = str(value).strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off"}:
                return False
        return default

    @staticmethod
    def _make_catalog_id(value: str | None, index: int) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip().lower()).strip("-")
        return normalized[:80] or f"model-{index + 1}"

    def _build_catalog_definition(self, raw: dict[str, Any], index: int) -> ChatModelDefinition:
        litellm_model = self._read_catalog_string(raw, "litellm_model", "litellm_name", "model_name", "model")
        if not litellm_model:
            raise ValueError("模型配置中的每个模型都必须配置 litellm_model")
        display_name = self._read_catalog_string(raw, "name", "model_name", "display_name") or litellm_model
        model_id = self._read_catalog_string(raw, "id", "model_id", "key") or self._make_catalog_id(display_name or litellm_model, index)
        return ChatModelDefinition(
            id=model_id,
            name=display_name,
            description=self._read_catalog_string(raw, "description", "desc") or "",
            is_premium=self._read_catalog_bool(raw, False, "is_premium", "is_advanced", "premium", "advanced"),
            icon_url=self._read_catalog_string(raw, "icon_url", "icon", "iconUri"),
            api_base=self._read_catalog_string(raw, "api_base", "api_address", "api_url", "base_url", "endpoint"),
            api_key=self._read_catalog_string(raw, "api_key", "apikey", "model_api_key"),
            litellm_model=litellm_model,
            supports_thinking_config=self._read_catalog_bool(
                raw,
                False,
                "supports_thinking_config",
                "supports_thinking",
                "thinking_configurable",
            ),
            default_thinking_mode=normalize_thinking_mode(
                self._read_catalog_string(raw, "default_thinking_mode", "thinking_mode"),
                "default",
            ),
        )

    def _resolve_model_catalog_file_path(self) -> Path | None:
        if not self.model_catalog_file:
            return None
        path = Path(self.model_catalog_file).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path

    def _load_json_from_file(self, path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"MODEL_CATALOG_FILE 指向的文件不存在: {path}") from exc
        except OSError as exc:
            raise ValueError(f"读取 MODEL_CATALOG_FILE 失败: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"MODEL_CATALOG_FILE 不是合法 JSON: {path}") from exc

    def _extract_available_models_payload(self, payload: Any) -> list[Any] | None:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            available_models = payload.get("available_models")
            if available_models is None:
                available_models = payload.get("models")
            if isinstance(available_models, list):
                return available_models
        return None

    def _resolve_configured_suggested_questions_model(self, payload: Any) -> ChatModelDefinition | None:
        if not isinstance(payload, dict) or "suggested_questions_model" not in payload:
            return None
        suggested_payload = payload.get("suggested_questions_model")
        if suggested_payload is None:
            return None
        if isinstance(suggested_payload, str):
            model = self.find_model_definition(suggested_payload)
            if model is None:
                raise ValueError("模型配置文件中的 suggested_questions_model 必须引用可选模型 id，或提供完整模型对象")
            return model
        if not isinstance(suggested_payload, dict):
            raise ValueError("模型配置文件中的 suggested_questions_model 必须是字符串或对象")
        return self._build_catalog_definition(suggested_payload, len(self.model_catalog))

    def _fallback_model_catalog(self) -> tuple[ChatModelDefinition, ...]:
        models = [
            ChatModelDefinition(
                id="default",
                name="默认模型",
                description="后端默认主力模型",
                is_premium=False,
                icon_url=None,
                api_base=None,
                api_key=None,
                litellm_model=self.default_chat_model,
                supports_thinking_config=True,
                default_thinking_mode=self.conversation_thinking_mode,
            )
        ]
        suggested_model = self.suggested_questions_model or self.default_chat_model
        if suggested_model != self.default_chat_model:
            models.append(
                ChatModelDefinition(
                    id="suggested-questions",
                    name="建议问题模型",
                    description="用于生成下一步建议问题的轻量模型",
                    is_premium=False,
                    icon_url=None,
                    api_base=None,
                    api_key=None,
                    litellm_model=suggested_model,
                    supports_thinking_config=True,
                    default_thinking_mode=self.suggested_questions_thinking_mode,
                )
            )
        return tuple(models)

    @cached_property
    def model_catalog_payload(self) -> Any:
        file_path = self._resolve_model_catalog_file_path()
        if file_path is not None:
            return self._load_json_from_file(file_path)
        if not self.model_catalog_json:
            return None
        try:
            return json.loads(self.model_catalog_json)
        except json.JSONDecodeError as exc:
            raise ValueError("MODEL_CATALOG_JSON 不是合法 JSON") from exc

    @cached_property
    def model_catalog(self) -> tuple[ChatModelDefinition, ...]:
        payload = self.model_catalog_payload
        if payload is None:
            return self._fallback_model_catalog()
        parsed = self._extract_available_models_payload(payload)
        if not isinstance(parsed, list) or not parsed:
            source_name = "MODEL_CATALOG_FILE" if self.model_catalog_file else "MODEL_CATALOG_JSON"
            raise ValueError(f"{source_name} 必须提供非空 available_models（或 models）数组")
        models: list[ChatModelDefinition] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise ValueError("模型配置中的每个可选模型都必须是对象")
            definition = self._build_catalog_definition(item, index)
            if definition.id in seen_ids:
                raise ValueError(f"模型配置包含重复模型 id: {definition.id}")
            seen_ids.add(definition.id)
            models.append(definition)
        return tuple(models)

    @cached_property
    def model_catalog_by_id(self) -> dict[str, ChatModelDefinition]:
        return {model.id: model for model in self.model_catalog}

    @cached_property
    def configured_suggested_questions_model_definition(self) -> ChatModelDefinition | None:
        return self._resolve_configured_suggested_questions_model(self.model_catalog_payload)

    def find_model_definition(self, value: str | None) -> ChatModelDefinition | None:
        if not value:
            return None
        normalized = value.strip()
        for model in self.model_catalog:
            if model.id == normalized or model.litellm_model == normalized:
                return model
        return None

    @property
    def effective_primary_model_id(self) -> str:
        if self.model_catalog_file:
            return self.model_catalog[0].id
        if self.default_primary_model_id:
            model = self.find_model_definition(self.default_primary_model_id)
            if model is None:
                raise ValueError("DEFAULT_PRIMARY_MODEL_ID 不在 MODEL_CATALOG_JSON 中")
            return model.id
        return self.model_catalog[0].id

    @property
    def effective_primary_model_definition(self) -> ChatModelDefinition:
        model = self.find_model_definition(self.effective_primary_model_id)
        if model is None:
            raise ValueError("默认主力模型配置无效")
        return model

    @property
    def effective_suggested_questions_model_definition(self) -> ChatModelDefinition:
        if self.configured_suggested_questions_model_definition is not None:
            return self.configured_suggested_questions_model_definition
        if self.suggested_questions_model_id:
            model = self.find_model_definition(self.suggested_questions_model_id)
            if model is None:
                raise ValueError("SUGGESTED_QUESTIONS_MODEL_ID 不在 MODEL_CATALOG_JSON 中")
            return model
        if self.suggested_questions_model:
            model = self.find_model_definition(self.suggested_questions_model)
            if model is not None:
                return model
            return ChatModelDefinition(
                id="suggested-questions",
                name="建议问题模型",
                description="用于生成下一步建议问题的轻量模型",
                is_premium=False,
                icon_url=None,
                api_base=None,
                api_key=None,
                litellm_model=self.suggested_questions_model,
                supports_thinking_config=True,
                default_thinking_mode=self.suggested_questions_thinking_mode,
            )
        return self.effective_primary_model_definition

    @property
    def effective_suggested_questions_thinking_mode(self) -> ThinkingMode:
        configured_model = self.configured_suggested_questions_model_definition
        if configured_model is not None:
            if not configured_model.supports_thinking_config:
                return "default"
            return configured_model.default_thinking_mode
        return self.suggested_questions_thinking_mode

    @property
    def artifact_root_path(self) -> Path:
        return Path(self.chat_artifact_root).resolve()

    @property
    def model_asset_root_path(self) -> Path:
        return Path(self.model_asset_root).resolve()

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
    def should_reload(self) -> bool:
        if self.app_reload is not None:
            return self.app_reload
        return self.app_env.lower() in {"local", "development", "dev"}

    @property
    def effective_adk_database_url(self) -> str:
        return self.adk_database_url or self.database_url

    @property
    def effective_text_model(self) -> str:
        return self.effective_primary_model_definition.litellm_model

    @property
    def effective_conversation_model(self) -> str:
        return self.effective_primary_model_definition.litellm_model

    @property
    def effective_xiaohongshu_model(self) -> str:
        return self.effective_primary_model_definition.litellm_model

    @property
    def effective_short_video_script_model(self) -> str:
        return self.effective_primary_model_definition.litellm_model

    @property
    def effective_suggested_questions_model(self) -> str:
        return self.effective_suggested_questions_model_definition.litellm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
