import json
import logging

import pytest
from sqlalchemy import select
from httpx import AsyncClient
from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.agents.run_config import StreamingMode

from app.api.schemas import ChatStreamRequest
from app.chat.agent_factory import WebAssistantModelConfig, create_web_assistant
from app.chat.runner import create_runner, get_adk_session_service
from app.chat.stream_service import ensure_adk_session, load_model_config, stream_chat_response
from app.core.config import Settings
from app.db.models import Conversation, Message, MessageArtifact, User, UserModelPreference
from app.db.session import AsyncSessionLocal


def parse_sse_events(body: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        payload: dict[str, str] = {}
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event: "):
                payload["event"] = line.removeprefix("event: ")
            if line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))
        if payload:
            payload["data"] = "\n".join(data_lines)
            events.append(payload)
    return events


class StubPart:
    def __init__(self, text: str, thought: bool):
        self.text = text
        self.thought = thought


class StubContent:
    def __init__(self, parts: list[StubPart]):
        self.parts = parts


class StubEvent:
    def __init__(self, text: str, *, thought: bool, partial: bool, final: bool, turn_complete: bool):
        self.content = StubContent([StubPart(text=text, thought=thought)])
        self.partial = partial
        self.turnComplete = turn_complete
        self._final = final

    def is_final_response(self) -> bool:
        return self._final

    def model_dump_json(self, exclude_none: bool = True, by_alias: bool = True) -> str:
        return json.dumps(
            {
                "content": {"parts": [{"text": self.content.parts[0].text, "thought": self.content.parts[0].thought}]},
                "partial": self.partial,
                "turnComplete": self.turnComplete,
            },
            ensure_ascii=False,
        )


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
    assert "event: adk_event" in body
    assert "event: persisted" in body
    assert "event: done" in body
    assert "event: delta" not in body

    events = parse_sse_events(body)
    conversation = next(event for event in events if event["event"] == "conversation")
    conversation_payload = json.loads(conversation["data"])
    assert conversation_payload["id"]
    assert conversation_payload["user_message_id"]
    adk_event = next(event for event in events if event["event"] == "adk_event")
    adk_payload = json.loads(adk_event["data"])
    assert adk_payload["content"]["parts"][0]["text"]
    assert adk_payload["turnComplete"] is True
    persisted = next(event for event in events if event["event"] == "persisted")
    assert json.loads(persisted["data"])["assistant_message_id"]


@pytest.mark.asyncio
async def test_stream_chat_uses_single_agent_team_entrypoint_in_adk_mode(monkeypatch: pytest.MonkeyPatch):
    async def fake_ensure_adk_session(*_: object, **__: object) -> None:
        return None

    captured_model_configs: list[WebAssistantModelConfig] = []

    class StubRunner:
        async def run_async(self, **_: object):
            yield StubEvent(text="生成完成", thought=False, partial=False, final=True, turn_complete=True)

    def fake_create_runner(model_config: WebAssistantModelConfig, settings: Settings):
        captured_model_configs.append(model_config)
        return StubRunner()

    monkeypatch.setattr("app.chat.stream_service.ensure_adk_session", fake_ensure_adk_session)
    monkeypatch.setattr("app.chat.stream_service.create_runner", fake_create_runner)

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        chat_agent_mode="adk",
        text_summary_model="default-text-model",
        conversation_model="default-conversation-model",
        xiaohongshu_model="default-xiaohongshu-model",
        short_video_script_model="default-short-video-script-model",
    )

    async with AsyncSessionLocal() as session:
        user = User(email="team-config@example.com", password_hash="hashed")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        session.add(
            UserModelPreference(
                user_id=user.id,
                text_summary_model="user-text-model",
                conversation_model="user-conversation-model",
                xiaohongshu_model="user-xiaohongshu-model",
                short_video_script_model="user-short-video-script-model",
            )
        )
        await session.commit()

        events = [
            event
            async for event in stream_chat_response(
                session,
                user.id,
                ChatStreamRequest(message="请结合网页改成小红书文案", context={"page_text": "网页正文"}, artifact_ids=[]),
                settings,
            )
        ]

    assert captured_model_configs == [
        WebAssistantModelConfig(
            conversation_model="user-conversation-model",
            text_summary_model="user-text-model",
            xiaohongshu_model="user-xiaohongshu-model",
            short_video_script_model="user-short-video-script-model",
        )
    ]
    assert any(event["event"] == "done" for event in events)


@pytest.mark.asyncio
async def test_stream_chat_returns_sse_error_when_generation_fails(
    authenticated_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    def failing_mock_response(prompt: str):
        raise RuntimeError("generation failed")

    monkeypatch.setattr("app.chat.stream_service.build_mock_response", failing_mock_response)

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
async def test_stream_chat_returns_generic_error_when_image_generation_fails(monkeypatch: pytest.MonkeyPatch):
    async def fake_ensure_adk_session(*_: object, **__: object) -> None:
        return None

    async def fake_load_artifact_parts(*_: object, **__: object) -> list[object]:
        return []

    class FailingRunner:
        async def run_async(self, **_: object):
            raise RuntimeError("model does not support image input")
            yield StubEvent(text="", thought=False, partial=False, final=False, turn_complete=False)

    monkeypatch.setattr("app.chat.stream_service.ensure_adk_session", fake_ensure_adk_session)
    monkeypatch.setattr("app.chat.stream_service.load_artifact_parts", fake_load_artifact_parts)
    monkeypatch.setattr("app.chat.stream_service.create_runner", lambda *_: FailingRunner())

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        chat_agent_mode="adk",
    )

    async with AsyncSessionLocal() as session:
        user = User(email="image-warning@example.com", password_hash="hashed")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        artifact = MessageArtifact(
            user_id=user.id,
            filename="screen.png",
            storage_filename="screen.png",
            mime_type="image/png",
            size_bytes=10,
            version=0,
            source="screenshot",
        )
        session.add(artifact)
        await session.commit()
        await session.refresh(artifact)

        events = [
            event
            async for event in stream_chat_response(
                session,
                user.id,
                ChatStreamRequest(message="请解释截图", context=None, artifact_ids=[artifact.id]),
                settings,
            )
        ]

    error_event = next(event for event in events if event["event"] == "error")
    assert error_event["data"] == "AI 响应生成失败，请稍后重试。"
    assert not any(event["event"] == "done" for event in events)


@pytest.mark.asyncio
async def test_stream_chat_falls_back_to_thought_text_when_no_visible_response(monkeypatch: pytest.MonkeyPatch):
    async def fake_ensure_adk_session(user_id: str, conversation: Conversation, settings: Settings) -> None:
        return None

    class StubRunner:
        async def run_async(self, **_: object):
            yield StubEvent("先整理信息。", thought=True, partial=True, final=False, turn_complete=False)
            yield StubEvent("先整理信息。最终答复。", thought=True, partial=False, final=True, turn_complete=True)

    monkeypatch.setattr("app.chat.stream_service.ensure_adk_session", fake_ensure_adk_session)
    monkeypatch.setattr("app.chat.stream_service.create_runner", lambda model_name, settings: StubRunner())

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        chat_agent_mode="adk",
    )

    async with AsyncSessionLocal() as session:
        user = User(email="tester@example.com", password_hash="hashed")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        events = [
            event
            async for event in stream_chat_response(
                session,
                user.id,
                ChatStreamRequest(message="你好", context=None, artifact_ids=[]),
                settings,
            )
        ]

    persisted = next(event for event in events if event["event"] == "persisted")
    assert json.loads(persisted["data"])["assistant_message_id"]

    async with AsyncSessionLocal() as session:
        assistant_messages = list(
            (
                await session.execute(
                    select(Message).where(Message.role == "assistant").order_by(Message.created_at)
                )
            ).scalars()
        )

    assert len(assistant_messages) == 1
    assert assistant_messages[0].content == "先整理信息。最终答复。"


@pytest.mark.asyncio
async def test_stream_chat_enables_adk_sse_streaming_mode(monkeypatch: pytest.MonkeyPatch):
    async def fake_ensure_adk_session(user_id: str, conversation: Conversation, settings: Settings) -> None:
        return None

    captured: dict[str, object] = {}

    class StubRunner:
        async def run_async(self, **kwargs: object):
            captured.update(kwargs)
            yield StubEvent("最终答复", thought=False, partial=False, final=True, turn_complete=True)

    monkeypatch.setattr("app.chat.stream_service.ensure_adk_session", fake_ensure_adk_session)
    monkeypatch.setattr("app.chat.stream_service.create_runner", lambda model_name, settings: StubRunner())

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        chat_agent_mode="adk",
    )

    async with AsyncSessionLocal() as session:
        user = User(email="runner@example.com", password_hash="hashed")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        _ = [
            event
            async for event in stream_chat_response(
                session,
                user.id,
                ChatStreamRequest(message="你好", context=None, artifact_ids=[]),
                settings,
            )
        ]

    run_config = captured.get("run_config")
    assert run_config is not None
    assert getattr(run_config, "streaming_mode", None) == StreamingMode.SSE


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


def test_create_runner_uses_model_config(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, object] = {}

    def fake_create_web_assistant(model_config: WebAssistantModelConfig):
        calls["model_config"] = model_config
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
    model_config = WebAssistantModelConfig(
        conversation_model="conversation-model",
        text_summary_model="summary-model",
        xiaohongshu_model="xiaohongshu-model",
        short_video_script_model="video-model",
    )

    create_runner(model_config, settings)

    assert calls["model_config"] == model_config
    assert calls["runner_kwargs"]["agent"] == "agent"
    assert calls["runner_kwargs"]["auto_create_session"] is False


def test_create_web_assistant_builds_delegating_agent_team():
    agent = create_web_assistant(
        WebAssistantModelConfig(
            conversation_model="conversation-model",
            text_summary_model="summary-model",
            xiaohongshu_model="xiaohongshu-model",
            short_video_script_model="video-model",
        )
    )

    sub_agent_names = {sub_agent.name for sub_agent in agent.sub_agents}
    assert agent.name == "summarix_web_assistant"
    assert sub_agent_names == {
        "summary_expert",
        "visual_context_expert",
        "xiaohongshu_copy_expert",
        "short_video_script_expert",
    }
    assert all(sub_agent.description for sub_agent in agent.sub_agents)


@pytest.mark.asyncio
async def test_load_model_config_uses_user_preferences_and_defaults():
    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        text_summary_model="default-text-model",
        conversation_model="default-conversation-model",
        xiaohongshu_model="default-xiaohongshu-model",
        short_video_script_model="default-short-video-script-model",
    )

    async with AsyncSessionLocal() as session:
        user = User(email="routing@example.com", password_hash="hashed")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        session.add(
            UserModelPreference(
                user_id=user.id,
                text_summary_model="user-text-model",
                conversation_model="user-conversation-model",
                xiaohongshu_model="user-xiaohongshu-model",
                short_video_script_model=None,
            )
        )
        await session.commit()

        model_config = await load_model_config(session, user.id, settings)

    assert model_config == WebAssistantModelConfig(
        conversation_model="user-conversation-model",
        text_summary_model="user-text-model",
        xiaohongshu_model="user-xiaohongshu-model",
        short_video_script_model="default-short-video-script-model",
    )
