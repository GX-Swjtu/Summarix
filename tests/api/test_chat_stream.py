import json
import logging

import pytest
from sqlalchemy import select
from httpx import AsyncClient
from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.agents.run_config import StreamingMode

from app.api.schemas import ChatStreamRequest
from app.chat.agent_factory import WebAssistantModelConfig, build_litellm_kwargs, create_web_assistant
from app.chat.runner import clear_runner_cache, create_runner, get_adk_session_service, get_or_create_runner
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
    def __init__(
        self,
        text: str,
        *,
        thought: bool,
        partial: bool,
        final: bool,
        turn_complete: bool,
        invocation_id: str | None = None,
    ):
        self.content = StubContent([StubPart(text=text, thought=thought)])
        self.partial = partial
        self.turnComplete = turn_complete
        self.invocation_id = invocation_id
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


def make_model_config(**overrides: str) -> WebAssistantModelConfig:
    values = {
        "conversation_model": "conversation-model",
        "text_summary_model": "summary-model",
        "xiaohongshu_model": "xiaohongshu-model",
        "short_video_script_model": "video-model",
        "suggested_questions_model": "suggestion-model",
        "conversation_thinking_mode": "default",
        "text_summary_thinking_mode": "default",
        "xiaohongshu_thinking_mode": "default",
        "short_video_script_thinking_mode": "default",
        "suggested_questions_thinking_mode": "default",
    }
    values.update(overrides)
    return WebAssistantModelConfig(**values)


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
    assert response.headers["x-trace-id"]
    body = response.text
    assert "event: conversation" in body
    assert "event: adk_event" in body
    assert "event: persisted" in body
    assert "event: done" in body
    assert "event: delta" not in body
    assert "event: suggested_questions" not in body

    events = parse_sse_events(body)
    conversation = next(event for event in events if event["event"] == "conversation")
    conversation_payload = json.loads(conversation["data"])
    assert conversation_payload["id"]
    assert conversation_payload["user_message_id"]
    assert conversation_payload["trace_id"]
    adk_event = next(event for event in events if event["event"] == "adk_event")
    adk_payload = json.loads(adk_event["data"])
    assert adk_payload["content"]["parts"][0]["text"]
    assert adk_payload["turnComplete"] is True
    persisted = next(event for event in events if event["event"] == "persisted")
    persisted_payload = json.loads(persisted["data"])
    assert persisted_payload["assistant_message_id"]
    assert persisted_payload["trace_id"] == conversation_payload["trace_id"]

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Message).where(Message.conversation_id == conversation_payload["id"]).order_by(Message.created_at))
        messages = result.scalars().all()
    assert [message.trace_id for message in messages] == [conversation_payload["trace_id"], conversation_payload["trace_id"]]


@pytest.mark.asyncio
async def test_stream_chat_emits_suggested_questions_when_requested(authenticated_client: AsyncClient):
    response = await authenticated_client.post(
        "/api/chat/stream",
        json={
            "message": "请总结页面",
            "context": {
                "page_url": "https://example.com",
                "page_title": "示例页面",
                "page_text": "这是一个用于建议问题测试的页面正文。",
            },
            "artifact_ids": [],
            "suggested_questions": True,
        },
    )

    assert response.status_code == 200
    events = parse_sse_events(response.text)
    event_names = [event["event"] for event in events]
    assert event_names.index("persisted") < event_names.index("done") < event_names.index("suggested_questions")
    payload = json.loads(next(event for event in events if event["event"] == "suggested_questions")["data"])
    assert payload["questions"] == [
        "这页内容最值得继续确认的关键结论是什么？",
        "有哪些风险、限制或待办需要优先处理？",
        "如果要把这些信息用于实际决策，下一步应该先问什么？",
    ]


@pytest.mark.asyncio
async def test_stream_suggested_questions_endpoint_returns_clickable_questions(authenticated_client: AsyncClient):
    chat_response = await authenticated_client.post(
        "/api/chat/stream",
        json={"message": "先建立一个会话", "context": None, "artifact_ids": []},
    )
    assert chat_response.status_code == 200
    conversation_id = json.loads(
        next(event for event in parse_sse_events(chat_response.text) if event["event"] == "conversation")["data"]
    )["id"]

    response = await authenticated_client.post(
        "/api/chat/suggestions/stream",
        json={"conversation_id": conversation_id, "count": 2},
    )

    assert response.status_code == 200
    events = parse_sse_events(response.text)
    assert [event["event"] for event in events] == ["suggested_questions", "done"]
    payload = json.loads(events[0]["data"])
    assert payload["questions"] == [
        "这页内容最值得继续确认的关键结论是什么？",
        "有哪些风险、限制或待办需要优先处理？",
    ]


@pytest.mark.asyncio
async def test_stream_chat_returns_page_reference_artifact(authenticated_client: AsyncClient):
    response = await authenticated_client.post(
        "/api/chat/stream",
        json={
            "message": "这篇文章讲了什么？",
            "context": {
                "page_url": "https://example.com/article",
                "page_title": "示例文章标题",
                "page_text": "第一段正文。\n第二段正文用于生成预览摘要。",
            },
            "artifact_ids": [],
        },
    )

    assert response.status_code == 200
    events = parse_sse_events(response.text)
    conversation_payload = json.loads(next(event for event in events if event["event"] == "conversation")["data"])
    reference = conversation_payload["reference_artifacts"][0]
    assert reference["source"] == "page_text"
    assert reference["page_url"] == "https://example.com/article"
    assert reference["page_title"] == "示例文章标题"
    assert reference["text_length"] == len("第一段正文。\n第二段正文用于生成预览摘要。")
    assert "第一段正文" in reference["text_excerpt"]
    assert reference["content_hash"]

    detail_response = await authenticated_client.get(f"/api/history/{conversation_payload['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    user_message = detail["messages"][0]
    assert user_message["artifacts"][0]["id"] == reference["id"]
    assert user_message["artifacts"][0]["source"] == "page_text"


@pytest.mark.asyncio
async def test_stream_chat_followup_without_context_does_not_create_page_reference(
    authenticated_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    captured_prompts: list[str] = []

    def capture_mock_response(prompt: str) -> str:
        captured_prompts.append(prompt)
        return "模拟回复"

    monkeypatch.setattr("app.chat.stream_service.build_mock_response", capture_mock_response)

    first_response = await authenticated_client.post(
        "/api/chat/stream",
        json={
            "message": "请总结这个页面",
            "context": {
                "page_url": "https://example.com/first",
                "page_title": "首轮页面",
                "page_text": "首轮页面正文，用来验证追问不会重复附加。",
            },
            "artifact_ids": [],
        },
    )
    assert first_response.status_code == 200
    first_events = parse_sse_events(first_response.text)
    first_payload = json.loads(next(event for event in first_events if event["event"] == "conversation")["data"])
    assert len(first_payload["reference_artifacts"]) == 1

    followup_response = await authenticated_client.post(
        "/api/chat/stream",
        json={
            "conversation_id": first_payload["id"],
            "message": "继续回答：这个页面最值得追问什么？",
            "context": None,
            "artifact_ids": [],
        },
    )
    assert followup_response.status_code == 200
    followup_events = parse_sse_events(followup_response.text)
    followup_payload = json.loads(next(event for event in followup_events if event["event"] == "conversation")["data"])
    assert followup_payload["id"] == first_payload["id"]
    assert followup_payload["user_message_id"]
    assert followup_payload["reference_artifacts"] == []
    assert any(event["event"] == "persisted" for event in followup_events)
    assert any(event["event"] == "done" for event in followup_events)
    assert len(captured_prompts) == 2
    assert "首轮页面正文，用来验证追问不会重复附加。" in captured_prompts[0]
    assert "本轮未附加新的网页正文，请沿用本会话历史中已经提供的网页上下文继续回答。" in captured_prompts[1]
    assert "历史页面标题：首轮页面" in captured_prompts[1]
    assert "历史页面 URL：https://example.com/first" in captured_prompts[1]
    assert "未提供网页上下文" not in captured_prompts[1]
    assert "首轮页面正文，用来验证追问不会重复附加。" not in captured_prompts[1]

    detail_response = await authenticated_client.get(f"/api/history/{first_payload['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["page_url"] == "https://example.com/first"
    assert len(detail["messages"]) == 4
    assert [artifact["source"] for artifact in detail["messages"][0]["artifacts"]] == ["page_text"]
    assert detail["messages"][2]["artifacts"] == []
    assert [artifact["source"] for artifact in detail["artifacts"]] == ["page_text"]


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
    monkeypatch.setattr("app.chat.stream_service.get_or_create_runner", fake_create_runner)

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        chat_agent_mode="adk",
        model_catalog_json=json.dumps(
            [
                {
                    "id": "fast",
                    "name": "Fast",
                    "description": "快速模型",
                    "litellm_model": "admin-fast-model",
                    "supports_thinking_config": True,
                },
                {
                    "id": "premium",
                    "name": "Premium",
                    "description": "高级模型",
                    "api_base": "https://premium.example.com/v1",
                    "api_key": "premium-secret",
                    "litellm_model": "admin-premium-model",
                    "supports_thinking_config": True,
                },
                {
                    "id": "suggestion",
                    "name": "Suggestion",
                    "description": "建议模型",
                    "litellm_model": "admin-suggestion-model",
                    "supports_thinking_config": False,
                },
            ]
        ),
        default_primary_model_id="fast",
        suggested_questions_model_id="suggestion",
    )

    async with AsyncSessionLocal() as session:
        user = User(email="team-config@example.com", password_hash="hashed")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        session.add(
            UserModelPreference(
                user_id=user.id,
                primary_model_id="premium",
                primary_thinking_mode="enabled",
                suggested_questions_model="legacy-user-suggestion-model",
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
        make_model_config(
            conversation_model="admin-premium-model",
            text_summary_model="admin-premium-model",
            xiaohongshu_model="admin-premium-model",
            short_video_script_model="admin-premium-model",
            suggested_questions_model="admin-suggestion-model",
            conversation_thinking_mode="enabled",
            text_summary_thinking_mode="enabled",
            xiaohongshu_thinking_mode="enabled",
            short_video_script_thinking_mode="enabled",
            suggested_questions_thinking_mode="default",
            primary_model_id="premium",
            primary_api_base="https://premium.example.com/v1",
            primary_api_key="premium-secret",
            suggested_questions_model_id="suggestion",
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
async def test_stream_chat_returns_image_unsupported_error_when_image_generation_fails(monkeypatch: pytest.MonkeyPatch):
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
    monkeypatch.setattr("app.chat.stream_service.get_or_create_runner", lambda *_: FailingRunner())

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
    assert error_event["data"] == "当前模型不支持图片输入，请更换支持图像输入的模型后重试。"
    assert not any(event["event"] == "done" for event in events)


@pytest.mark.asyncio
async def test_stream_chat_keeps_generic_error_when_no_image_artifact(monkeypatch: pytest.MonkeyPatch):
    async def fake_ensure_adk_session(*_: object, **__: object) -> None:
        return None

    class FailingRunner:
        async def run_async(self, **_: object):
            raise RuntimeError("model does not support image input")
            yield StubEvent(text="", thought=False, partial=False, final=False, turn_complete=False)

    monkeypatch.setattr("app.chat.stream_service.ensure_adk_session", fake_ensure_adk_session)
    monkeypatch.setattr("app.chat.stream_service.get_or_create_runner", lambda *_: FailingRunner())

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        chat_agent_mode="adk",
    )

    async with AsyncSessionLocal() as session:
        user = User(email="text-only-error@example.com", password_hash="hashed")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        events = [
            event
            async for event in stream_chat_response(
                session,
                user.id,
                ChatStreamRequest(message="普通文本问题", context=None, artifact_ids=[]),
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
    monkeypatch.setattr("app.chat.stream_service.get_or_create_runner", lambda model_config, settings: StubRunner())

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
    monkeypatch.setattr("app.chat.stream_service.get_or_create_runner", lambda model_config, settings: StubRunner())

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
async def test_stream_chat_records_adk_invocation_id_on_messages_and_reference(monkeypatch: pytest.MonkeyPatch):
    async def fake_ensure_adk_session(user_id: str, conversation: Conversation, settings: Settings) -> None:
        return None

    class StubRunner:
        async def run_async(self, **_: object):
            yield StubEvent(
                "最终答复",
                thought=False,
                partial=False,
                final=True,
                turn_complete=True,
                invocation_id="invocation-123",
            )

    monkeypatch.setattr("app.chat.stream_service.ensure_adk_session", fake_ensure_adk_session)
    monkeypatch.setattr("app.chat.stream_service.get_or_create_runner", lambda model_config, settings: StubRunner())

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        chat_agent_mode="adk",
    )

    async with AsyncSessionLocal() as session:
        user = User(email="invocation@example.com", password_hash="hashed")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        events = [
            event
            async for event in stream_chat_response(
                session,
                user.id,
                ChatStreamRequest(
                    message="请总结",
                    context={
                        "page_url": "https://example.com/source",
                        "page_title": "事件追踪页面",
                        "page_text": "用于追踪 ADK invocation 的网页正文。",
                    },
                    artifact_ids=[],
                ),
                settings,
            )
        ]

        messages = list(
            (
                await session.execute(
                    select(Message).where(Message.conversation_id == json.loads(events[0]["data"])["id"]).order_by(Message.created_at)
                )
            ).scalars()
        )
        reference = (
            await session.execute(
                select(MessageArtifact).where(
                    MessageArtifact.message_id == messages[0].id,
                    MessageArtifact.source == "page_text",
                )
            )
        ).scalar_one()

    assert messages[0].adk_invocation_id == "invocation-123"
    assert messages[1].adk_invocation_id == "invocation-123"
    assert reference.adk_invocation_id == "invocation-123"


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
    model_config = make_model_config(
        conversation_model="conversation-model",
        text_summary_model="summary-model",
        xiaohongshu_model="xiaohongshu-model",
        short_video_script_model="video-model",
    )

    create_runner(model_config, settings)

    assert calls["model_config"] == model_config
    assert calls["runner_kwargs"]["agent"] == "agent"
    assert calls["runner_kwargs"]["auto_create_session"] is False


def test_get_or_create_runner_reuses_same_model_config(monkeypatch: pytest.MonkeyPatch):
    clear_runner_cache()
    calls = {"count": 0}

    class StubRunner:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fake_create_web_assistant(model_config: WebAssistantModelConfig):
        calls["count"] += 1
        return {"model_config": model_config}

    monkeypatch.setattr("app.chat.runner.create_web_assistant", fake_create_web_assistant)
    monkeypatch.setattr("app.chat.runner.Runner", StubRunner)
    monkeypatch.setattr("app.chat.runner.get_adk_session_service", lambda settings: "session-service")
    monkeypatch.setattr("app.chat.runner.get_artifact_service", lambda: "artifact-service")

    settings = Settings(jwt_secret_key="x" * 32, database_url="sqlite+aiosqlite:///:memory:")
    model_config = make_model_config(conversation_model="same-model", primary_model_id="same")

    runner_a = get_or_create_runner(model_config, settings)
    runner_b = get_or_create_runner(make_model_config(conversation_model="same-model", primary_model_id="same"), settings)

    assert runner_a is runner_b
    assert calls["count"] == 1
    clear_runner_cache()


def test_get_or_create_runner_separates_different_model_configs(monkeypatch: pytest.MonkeyPatch):
    clear_runner_cache()
    calls = {"count": 0}

    class StubRunner:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def fake_create_web_assistant(model_config: WebAssistantModelConfig):
        calls["count"] += 1
        return {"model_config": model_config}

    monkeypatch.setattr("app.chat.runner.create_web_assistant", fake_create_web_assistant)
    monkeypatch.setattr("app.chat.runner.Runner", StubRunner)
    monkeypatch.setattr("app.chat.runner.get_adk_session_service", lambda settings: "session-service")
    monkeypatch.setattr("app.chat.runner.get_artifact_service", lambda: "artifact-service")

    settings = Settings(jwt_secret_key="x" * 32, database_url="sqlite+aiosqlite:///:memory:")
    runner_a = get_or_create_runner(make_model_config(conversation_model="model-a", primary_model_id="a"), settings)
    runner_b = get_or_create_runner(make_model_config(conversation_model="model-b", primary_model_id="b"), settings)

    assert runner_a is not runner_b
    assert calls["count"] == 2
    clear_runner_cache()


def test_build_litellm_kwargs_respects_thinking_mode():
    assert build_litellm_kwargs("default") == {}
    assert build_litellm_kwargs("enabled") == {"extra_body": {"enable_thinking": True}}
    assert build_litellm_kwargs("disabled") == {"extra_body": {"enable_thinking": False}}


def test_create_web_assistant_builds_delegating_agent_team():
    agent = create_web_assistant(
        make_model_config(
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
    xiaohongshu_agent = next(
        sub_agent for sub_agent in agent.sub_agents if sub_agent.name == "xiaohongshu_copy_expert"
    )
    assert "至少出现 6 个表情" in xiaohongshu_agent.instruction
    assert "少用“首先、其次、最后、总结来说”这类总结腔" in xiaohongshu_agent.instruction
    assert "直接输出一篇用户可以复制粘贴发布的小红书成品文案" in xiaohongshu_agent.instruction
    assert "不要再用“爆点标题”“开场引子”“正文”“标签”“互动引导”这类小节标题" in xiaohongshu_agent.instruction


def test_create_web_assistant_applies_thinking_mode_to_litellm_models(monkeypatch: pytest.MonkeyPatch):
    import app.chat.agent_factory as agent_factory_module

    calls: list[tuple[str, str]] = []
    original = agent_factory_module.create_litellm

    def spy_create_litellm(model_name: str, thinking_mode: str, **kwargs: object):
        calls.append((model_name, thinking_mode))
        return original(model_name, thinking_mode, **kwargs)

    monkeypatch.setattr(agent_factory_module, "create_litellm", spy_create_litellm)

    create_web_assistant(
        make_model_config(
            conversation_model="conv-model",
            text_summary_model="summary-model",
            xiaohongshu_model="xhs-model",
            short_video_script_model="video-model",
            conversation_thinking_mode="enabled",
            text_summary_thinking_mode="disabled",
            xiaohongshu_thinking_mode="default",
            short_video_script_thinking_mode="enabled",
        )
    )

    thinking_by_model = dict(calls)
    assert thinking_by_model["summary-model"] == "disabled"
    assert thinking_by_model["xhs-model"] == "default"
    assert thinking_by_model["video-model"] == "enabled"
    assert thinking_by_model["conv-model"] == "enabled"


@pytest.mark.asyncio
async def test_load_model_config_uses_user_preferences_and_defaults():
    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        model_catalog_json=json.dumps(
            [
                {
                    "id": "fast",
                    "name": "Fast",
                    "description": "默认主力",
                    "litellm_model": "default-primary-model",
                    "supports_thinking_config": True,
                    "default_thinking_mode": "disabled",
                },
                {
                    "id": "writer",
                    "name": "Writer",
                    "description": "用户主力",
                    "litellm_model": "user-primary-model",
                    "supports_thinking_config": True,
                },
                {
                    "id": "suggestion",
                    "name": "Suggestion",
                    "description": "建议问题",
                    "api_base": "https://suggestion.example.com/v1",
                    "api_key": "suggestion-secret",
                    "litellm_model": "admin-suggestion-model",
                    "supports_thinking_config": True,
                },
            ]
        ),
        default_primary_model_id="fast",
        suggested_questions_model_id="suggestion",
        suggested_questions_thinking_mode="disabled",
    )

    async with AsyncSessionLocal() as session:
        user = User(email="routing@example.com", password_hash="hashed")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        session.add(
            UserModelPreference(
                user_id=user.id,
                primary_model_id="writer",
                primary_thinking_mode="enabled",
                suggested_questions_model="legacy-user-suggestion-model",
            )
        )
        await session.commit()

        model_config = await load_model_config(session, user.id, settings)

    assert model_config == make_model_config(
        conversation_model="user-primary-model",
        text_summary_model="user-primary-model",
        xiaohongshu_model="user-primary-model",
        short_video_script_model="user-primary-model",
        suggested_questions_model="admin-suggestion-model",
        conversation_thinking_mode="enabled",
        text_summary_thinking_mode="enabled",
        xiaohongshu_thinking_mode="enabled",
        short_video_script_thinking_mode="enabled",
        suggested_questions_thinking_mode="disabled",
        primary_model_id="writer",
        suggested_questions_model_id="suggestion",
        suggested_questions_api_base="https://suggestion.example.com/v1",
        suggested_questions_api_key="suggestion-secret",
    )
