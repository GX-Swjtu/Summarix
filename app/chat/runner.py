from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService

from app.chat.agent_factory import WebAssistantModelConfig, create_web_assistant
from app.chat.artifacts import get_artifact_service
from app.core.config import Settings, get_settings


_session_services: dict[str, DatabaseSessionService] = {}


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
