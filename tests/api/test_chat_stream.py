import logging

import pytest
from httpx import AsyncClient
from google.adk.errors.already_exists_error import AlreadyExistsError

from app.chat.runner import create_runner, get_adk_session_service
from app.chat.stream_service import ensure_adk_session
from app.core.config import Settings
from app.db.models import Conversation


@pytest.mark.asyncio
async def test_stream_chat_returns_sse_and_records_messages(authenticated_client: AsyncClient):
    response = await authenticated_client.post(
        "/api/chat/stream",
        json={
            "message": "请总结页面",
            "context": {
                "page_url": "https://example.com",
                "page_title": "示例页面",
                "page_text": "这是一个用于测试的页面正文。",
            },
            "artifact_ids": [],
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: conversation" in body
    assert "event: delta" in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_stream_chat_returns_sse_error_when_generation_fails(
    authenticated_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    async def failing_mock_stream(prompt: str):
        if False:
            yield prompt
        raise RuntimeError("generation failed")

    monkeypatch.setattr("app.chat.stream_service.run_mock_stream", failing_mock_stream)

    with caplog.at_level(logging.ERROR, logger="app.chat.stream_service"):
        response = await authenticated_client.post(
            "/api/chat/stream",
            json={"message": "触发错误", "context": None, "artifact_ids": []},
        )

    assert response.status_code == 200
    body = response.text
    assert "event: conversation" in body
    assert "event: error" in body
    assert "AI 响应生成失败" in body
    assert "event: done" not in body
    assert "AI 响应生成失败" in caplog.text


@pytest.mark.asyncio
async def test_ensure_adk_session_uses_database_session_service(tmp_path):
    adk_db = tmp_path / "adk_sessions.db"
    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url=f"sqlite+aiosqlite:///{adk_db.as_posix()}",
        chat_agent_mode="adk",
    )
    conversation = Conversation(user_id="user-id", adk_session_id="session-id")

    await ensure_adk_session("user-id", conversation, settings)

    session_service = get_adk_session_service(settings)
    adk_session = await session_service.get_session(
        app_name=settings.chat_app_name,
        user_id="user-id",
        session_id="session-id",
    )
    assert adk_session is not None
    assert adk_session.id == "session-id"


@pytest.mark.asyncio
async def test_ensure_adk_session_ignores_duplicate_creation(monkeypatch: pytest.MonkeyPatch):
    calls = {"get": 0, "create": 0}

    class StubSessionService:
        async def get_session(self, **_: str):
            calls["get"] += 1
            return None

        async def create_session(self, **_: str):
            calls["create"] += 1
            raise AlreadyExistsError("Session already exists")

    monkeypatch.setattr("app.chat.stream_service.get_adk_session_service", lambda settings: StubSessionService())

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        chat_agent_mode="adk",
    )
    conversation = Conversation(user_id="user-id", adk_session_id="session-id")

    await ensure_adk_session("user-id", conversation, settings)

    assert calls == {"get": 1, "create": 1}


@pytest.mark.asyncio
async def test_ensure_adk_session_auto_creates_separate_database(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    class StubSessionService:
        async def get_session(self, **_: str):
            calls.append(("get", "session-id"))
            return None

        async def create_session(self, **_: str):
            calls.append(("create", "session-id"))

    async def fake_ensure_database_exists(database_url: str):
        calls.append(("db", database_url))

    monkeypatch.setattr("app.chat.stream_service.ensure_database_exists", fake_ensure_database_exists)
    monkeypatch.setattr("app.chat.stream_service.get_adk_session_service", lambda settings: StubSessionService())

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        database_auto_create_database=True,
        adk_database_url="postgresql+asyncpg://tester:secret@db.example.com:5432/summarix-adk",
        chat_agent_mode="adk",
    )
    conversation = Conversation(user_id="user-id", adk_session_id="session-id")

    await ensure_adk_session("user-id", conversation, settings)

    assert calls == [
        ("db", settings.effective_adk_database_url),
        ("get", "session-id"),
        ("create", "session-id"),
    ]


def test_create_runner_uses_configured_model_name(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, object] = {}

    def fake_create_web_assistant(model_name: str):
        calls["model_name"] = model_name
        return "agent"

    class StubRunner:
        def __init__(self, **kwargs):
            calls["runner_kwargs"] = kwargs

    monkeypatch.setattr("app.chat.runner.create_web_assistant", fake_create_web_assistant)
    monkeypatch.setattr("app.chat.runner.Runner", StubRunner)
    monkeypatch.setattr("app.chat.runner.get_adk_session_service", lambda settings: "session-service")
    monkeypatch.setattr("app.chat.runner.get_artifact_service", lambda: "artifact-service")

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
    )

    create_runner("dashscope/qwen3.5-flash", settings)

    assert calls["model_name"] == "dashscope/qwen3.5-flash"
