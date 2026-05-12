import logging

import pytest
from httpx import AsyncClient
from google.adk.errors.already_exists_error import AlreadyExistsError

from app.chat.runner import get_adk_session_service
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
