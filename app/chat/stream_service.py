from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from google.adk.errors.already_exists_error import AlreadyExistsError
from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ChatStreamRequest
from app.chat.artifacts import get_artifact_service
from app.chat.runner import create_runner, get_adk_session_service
from app.core.config import Settings, get_settings
from app.db.init import ensure_database_exists
from app.db.models import Conversation, Message, MessageArtifact, UserModelPreference


logger = logging.getLogger(__name__)


async def ensure_adk_session(user_id: str, conversation: Conversation, settings: Settings) -> None:
    if settings.chat_agent_mode != "adk":
        return
    if settings.database_auto_create_database:
        await ensure_database_exists(settings.effective_adk_database_url)
    session_service = get_adk_session_service(settings)
    adk_session = await session_service.get_session(
        app_name=settings.chat_app_name,
        user_id=user_id,
        session_id=conversation.adk_session_id,
    )
    if adk_session is None:
        try:
            await session_service.create_session(
                app_name=settings.chat_app_name,
                user_id=user_id,
                session_id=conversation.adk_session_id,
            )
        except AlreadyExistsError:
            pass


async def get_or_create_conversation(session: AsyncSession, user_id: str, request: ChatStreamRequest, settings: Settings) -> Conversation:
    if request.conversation_id:
        result = await session.execute(
            select(Conversation).where(Conversation.id == request.conversation_id, Conversation.user_id == user_id)
        )
        conversation = result.scalar_one_or_none()
        if conversation is not None:
            await ensure_adk_session(user_id, conversation, settings)
            return conversation
    title = request.context.page_title if request.context and request.context.page_title else request.message[:40]
    conversation = Conversation(
        user_id=user_id,
        title=title or "新会话",
        page_url=request.context.page_url if request.context else None,
        page_title=request.context.page_title if request.context else None,
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    await ensure_adk_session(user_id, conversation, settings)
    return conversation


async def choose_model(session: AsyncSession, user_id: str, request: ChatStreamRequest, settings: Settings) -> str:
    result = await session.execute(select(UserModelPreference).where(UserModelPreference.user_id == user_id))
    preference = result.scalar_one_or_none()
    has_artifact = bool(request.artifact_ids)
    if has_artifact:
        return (preference.vision_analysis_model if preference else None) or settings.effective_vision_model
    return (preference.conversation_model if preference else None) or settings.effective_conversation_model


async def build_prompt(session: AsyncSession, user_id: str, conversation: Conversation, request: ChatStreamRequest) -> str:
    lines = []
    if request.context:
        if request.context.page_title:
            lines.append(f"网页标题：{request.context.page_title}")
        if request.context.page_url:
            lines.append(f"网页地址：{request.context.page_url}")
        if request.context.page_text:
            lines.append("网页正文：")
            lines.append(request.context.page_text[:30000])
    if request.artifact_ids:
        result = await session.execute(
            select(MessageArtifact).where(
                MessageArtifact.id.in_(request.artifact_ids),
                MessageArtifact.user_id == user_id,
            )
        )
        artifacts = result.scalars().all()
        if artifacts:
            lines.append("已上传附件：")
            for artifact in artifacts:
                artifact.conversation_id = conversation.id
                lines.append(f"- {artifact.filename} ({artifact.mime_type}, artifact_id={artifact.id})")
    lines.append("用户问题：")
    lines.append(request.message)
    await session.commit()
    return "\n".join(lines)


async def load_artifact_parts(
    session: AsyncSession,
    user_id: str,
    request: ChatStreamRequest,
    settings: Settings,
) -> list[types.Part]:
    if not request.artifact_ids:
        return []
    result = await session.execute(
        select(MessageArtifact).where(
            MessageArtifact.id.in_(request.artifact_ids),
            MessageArtifact.user_id == user_id,
        )
    )
    artifacts = result.scalars().all()
    parts: list[types.Part] = []
    for artifact in artifacts:
        part = await get_artifact_service().load_artifact(
            app_name=settings.chat_app_name,
            user_id=user_id,
            filename=f"user:{artifact.storage_filename}",
            version=artifact.version,
        )
        if part is not None:
            parts.append(part)
    return parts


def extract_event_text(event: object) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    text_chunks = [part.text for part in parts if getattr(part, "text", None)]
    return "".join(text_chunks)


async def run_mock_stream(prompt: str) -> AsyncIterator[str]:
    text = "这是本地开发模式下的模拟回复。已收到网页上下文和用户问题，可以在配置模型密钥后切换到真实 ADK 流式响应。"
    if "网页标题：" in prompt:
        text += "我会优先结合网页标题、正文和截图附件进行总结。"
    for chunk in text.split("，"):
        yield chunk + "，"


async def stream_chat_response(
    session: AsyncSession,
    user_id: str,
    request: ChatStreamRequest,
    settings: Settings | None = None,
) -> AsyncIterator[dict[str, str]]:
    settings = settings or get_settings()
    conversation = await get_or_create_conversation(session, user_id, request, settings)
    prompt = await build_prompt(session, user_id, conversation, request)
    user_message = Message(conversation_id=conversation.id, role="user", content=request.message)
    session.add(user_message)
    await session.commit()
    yield {"event": "conversation", "data": conversation.id}

    full_response = ""
    try:
        if settings.chat_agent_mode == "mock":
            async for chunk in run_mock_stream(prompt):
                full_response += chunk
                yield {"event": "delta", "data": chunk}
        else:
            model_name = await choose_model(session, user_id, request, settings)
            runner = create_runner(model_name, settings)
            message_parts = [types.Part.from_text(text=prompt), *await load_artifact_parts(session, user_id, request, settings)]
            async for event in runner.run_async(
                user_id=user_id,
                session_id=conversation.adk_session_id,
                new_message=types.Content(role="user", parts=message_parts),
            ):
                chunk = extract_event_text(event)
                if not chunk:
                    continue
                full_response += chunk
                yield {"event": "delta", "data": chunk}
    except Exception:
        logger.exception("AI 响应生成失败，user_id=%s conversation_id=%s", user_id, conversation.id)
        yield {"event": "error", "data": "AI 响应生成失败，请稍后重试。"}
        return

    assistant_message = Message(conversation_id=conversation.id, role="assistant", content=full_response)
    session.add(assistant_message)
    await session.commit()
    yield {"event": "done", "data": assistant_message.id}
