import hashlib
import json
from threading import Lock

from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService

from app.chat.agent_factory import WebAssistantModelConfig, create_web_assistant
from app.chat.artifacts import get_artifact_service
from app.core.config import Settings, get_settings


_session_services: dict[str, DatabaseSessionService] = {}
_runner_cache: dict[str, Runner] = {}
_runner_cache_lock = Lock()


def get_adk_session_service(settings: Settings | None = None) -> DatabaseSessionService:
    settings = settings or get_settings()
    db_url = settings.effective_adk_database_url
    if db_url not in _session_services:
        _session_services[db_url] = DatabaseSessionService(db_url=db_url)
    return _session_services[db_url]


def create_runner(model_config: WebAssistantModelConfig, settings: Settings | None = None) -> Runner:
    settings = settings or get_settings()
    return Runner(
        agent=create_web_assistant(model_config),
        app_name=settings.chat_app_name,
        session_service=get_adk_session_service(settings),
        artifact_service=get_artifact_service(),
        auto_create_session=False,
    )


def _secret_fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_runner_cache_key(model_config: WebAssistantModelConfig, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    payload = {
        "app_name": settings.chat_app_name,
        "adk_database_url": settings.effective_adk_database_url,
        "primary_model_id": model_config.primary_model_id,
        "conversation_model": model_config.conversation_model,
        "text_summary_model": model_config.text_summary_model,
        "xiaohongshu_model": model_config.xiaohongshu_model,
        "short_video_script_model": model_config.short_video_script_model,
        "conversation_thinking_mode": model_config.conversation_thinking_mode,
        "text_summary_thinking_mode": model_config.text_summary_thinking_mode,
        "xiaohongshu_thinking_mode": model_config.xiaohongshu_thinking_mode,
        "short_video_script_thinking_mode": model_config.short_video_script_thinking_mode,
        "primary_api_base": model_config.primary_api_base,
        "primary_api_key_fingerprint": _secret_fingerprint(model_config.primary_api_key),
    }
    raw_key = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_or_create_runner(model_config: WebAssistantModelConfig, settings: Settings | None = None) -> Runner:
    settings = settings or get_settings()
    cache_key = build_runner_cache_key(model_config, settings)
    with _runner_cache_lock:
        runner = _runner_cache.get(cache_key)
        if runner is None:
            runner = create_runner(model_config, settings)
            _runner_cache[cache_key] = runner
        return runner


def clear_runner_cache() -> None:
    with _runner_cache_lock:
        _runner_cache.clear()
