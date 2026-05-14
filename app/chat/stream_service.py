from __future__ import annotations

import logging
import json
import re
from collections.abc import AsyncIterator, Sequence

from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ChatStreamRequest, SuggestedQuestionsStreamRequest
from app.chat.agent_factory import WebAssistantModelConfig, build_litellm_kwargs
from app.chat.artifacts import get_artifact_service, save_page_text_artifact
from app.chat.runner import create_runner, get_adk_session_service
from app.core.config import Settings, get_settings
from app.db.init import ensure_database_exists
from app.db.models import Conversation, Message, MessageArtifact, UserModelPreference


logger = logging.getLogger(__name__)

IMAGE_UNSUPPORTED_ERROR_MESSAGE = "当前模型不支持图片输入，请更换支持图像输入的模型后重试。"
GENERIC_STREAM_ERROR_MESSAGE = "AI 响应生成失败，请稍后重试。"
IMAGE_UNSUPPORTED_ERROR_PATTERNS = (
    "does not support image",
    "doesn't support image",
    "image input",
    "image is not supported",
    "vision input",
    "vision is not supported",
    "multimodal",
)
PAGE_TEXT_PROMPT_LIMIT = 30000
SUGGESTED_QUESTIONS_CONTEXT_LIMIT = 12000
SUGGESTED_QUESTIONS_RECENT_MESSAGE_LIMIT = 8

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


async def load_model_config(session: AsyncSession, user_id: str, settings: Settings) -> WebAssistantModelConfig:
    result = await session.execute(select(UserModelPreference).where(UserModelPreference.user_id == user_id))
    preference = result.scalar_one_or_none()
    return WebAssistantModelConfig(
        conversation_model=(preference.conversation_model if preference else None) or settings.effective_conversation_model,
        text_summary_model=(preference.text_summary_model if preference else None) or settings.effective_text_model,
        xiaohongshu_model=(preference.xiaohongshu_model if preference else None) or settings.effective_xiaohongshu_model,
        short_video_script_model=(preference.short_video_script_model if preference else None)
        or settings.effective_short_video_script_model,
        suggested_questions_model=(preference.suggested_questions_model if preference else None)
        or settings.effective_suggested_questions_model,
        conversation_thinking_mode=(preference.conversation_thinking_mode if preference else None)
        or settings.conversation_thinking_mode,
        text_summary_thinking_mode=(preference.text_summary_thinking_mode if preference else None)
        or settings.text_summary_thinking_mode,
        xiaohongshu_thinking_mode=(preference.xiaohongshu_thinking_mode if preference else None)
        or settings.xiaohongshu_thinking_mode,
        short_video_script_thinking_mode=(preference.short_video_script_thinking_mode if preference else None)
        or settings.short_video_script_thinking_mode,
        suggested_questions_thinking_mode=(preference.suggested_questions_thinking_mode if preference else None)
        or settings.suggested_questions_thinking_mode,
    )


async def load_request_artifacts(session: AsyncSession, user_id: str, artifact_ids: Sequence[str]) -> list[MessageArtifact]:
    if not artifact_ids:
        return []
    result = await session.execute(
        select(MessageArtifact).where(
            MessageArtifact.id.in_(artifact_ids),
            MessageArtifact.user_id == user_id,
        )
    )
    return list(result.scalars().all())


def has_image_artifacts(artifacts: Sequence[MessageArtifact]) -> bool:
    return any((artifact.mime_type or "").startswith("image/") for artifact in artifacts)


def is_image_unsupported_error(error: Exception, artifacts: Sequence[MessageArtifact]) -> bool:
    if not has_image_artifacts(artifacts):
        return False
    message = str(error).lower()
    return any(pattern in message for pattern in IMAGE_UNSUPPORTED_ERROR_PATTERNS)


def build_prompt(request: ChatStreamRequest, artifacts: Sequence[MessageArtifact], conversation: Conversation | None = None) -> str:
    lines = [
        "请作为 Summarix 浏览器助手回答用户问题。",
        "输出要求：默认使用简体中文；使用清晰 Markdown；只基于已提供的网页、URL、截图或对话上下文作答；无法确认时请说明。",
    ]
    lines.extend(["", "## 当前网页上下文"])
    if request.context:
        if request.context.page_title:
            lines.append(f"- 标题：{request.context.page_title}")
        if request.context.page_url:
            lines.append(f"- URL：{request.context.page_url}")
        if request.context.page_text:
            lines.append(f"- 正文长度：{len(request.context.page_text)} 字符")
            lines.append("")
            lines.append("### 网页正文")
            lines.append(request.context.page_text[:PAGE_TEXT_PROMPT_LIMIT])
        if not request.context.page_title and not request.context.page_url and not request.context.page_text:
            lines.append("- 未提供网页正文、标题或 URL。")
    elif conversation and (conversation.page_title or conversation.page_url):
        lines.append("- 本轮未附加新的网页正文，请沿用本会话历史中已经提供的网页上下文继续回答。")
        lines.append("- 不要仅因为本轮未重新附加正文就判断缺少网页内容；只有历史上下文确实不足时才说明无法确认。")
        if conversation.page_title:
            lines.append(f"- 历史页面标题：{conversation.page_title}")
        if conversation.page_url:
            lines.append(f"- 历史页面 URL：{conversation.page_url}")
    else:
        lines.append("- 未提供网页上下文。")
    lines.append("")
    lines.append("## 附件")
    if artifacts:
        for artifact in artifacts:
            lines.append(f"- {artifact.filename} ({artifact.mime_type}, artifact_id={artifact.id})")
    else:
        lines.append("- 未提供附件。")
    lines.append("")
    lines.append("## 用户问题")
    lines.append("用户问题：")
    lines.append(request.message)
    return "\n".join(lines)


async def load_artifact_parts(
    artifacts: Sequence[MessageArtifact],
    settings: Settings,
) -> list[types.Part]:
    parts: list[types.Part] = []
    for artifact in artifacts:
        part = await get_artifact_service().load_artifact(
            app_name=settings.chat_app_name,
            user_id=artifact.user_id,
            filename=f"user:{artifact.storage_filename}",
            version=artifact.version,
        )
        if part is not None:
            parts.append(part)
    return parts


def merge_complete_text(current: str, incoming: str) -> str:
    if not current or incoming.startswith(current):
        return incoming
    if current.startswith(incoming):
        return current
    return current + incoming


def extract_event_texts(event: object) -> tuple[str, str]:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    visible_chunks: list[str] = []
    thought_chunks: list[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        if not text:
            continue
        if getattr(part, "thought", False):
            thought_chunks.append(text)
        else:
            visible_chunks.append(text)
    return "".join(visible_chunks), "".join(thought_chunks)


def is_final_response(event: object) -> bool:
    checker = getattr(event, "is_final_response", None)
    if checker is None:
        return False
    try:
        return bool(checker())
    except Exception:
        return False


def serialize_adk_event(event: object) -> str:
    serializer = getattr(event, "model_dump_json", None)
    if serializer is not None:
        return serializer(exclude_none=True, by_alias=True)
    return json.dumps(event, ensure_ascii=False)


def get_event_invocation_id(event: object) -> str | None:
    invocation_id = getattr(event, "invocation_id", None) or getattr(event, "invocationId", None)
    return str(invocation_id) if invocation_id else None


def serialize_artifact_payload(artifact: MessageArtifact) -> dict[str, object]:
    return {
        "id": artifact.id,
        "filename": artifact.filename,
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
        "version": artifact.version,
        "source": artifact.source,
        "page_url": artifact.page_url,
        "page_title": artifact.page_title,
        "text_excerpt": artifact.text_excerpt,
        "text_length": artifact.text_length,
        "content_hash": artifact.content_hash,
        "adk_invocation_id": artifact.adk_invocation_id,
    }


def has_reference_context(request: ChatStreamRequest) -> bool:
    if not request.context:
        return False
    return bool(request.context.page_title or request.context.page_url or request.context.page_text)


def mock_adk_event(text: str) -> dict[str, object]:
    return {
        "author": "summarix_web_assistant",
        "content": {"role": "model", "parts": [{"text": text}]},
        "partial": False,
        "turnComplete": True,
    }


def build_mock_response(prompt: str) -> str:
    text = "这是本地开发模式下的模拟回复。已收到网页上下文和用户问题，可以在配置模型密钥后切换到真实 ADK 流式响应。"
    if "### 网页正文" in prompt or "- 标题：" in prompt:
        text += "我会优先结合网页标题、正文和截图附件进行总结。"
    return text


def build_mock_suggested_questions(count: int) -> list[str]:
    questions = [
        "这页内容最值得继续确认的关键结论是什么？",
        "有哪些风险、限制或待办需要优先处理？",
        "如果要把这些信息用于实际决策，下一步应该先问什么？",
        "当前信息里有哪些地方需要更多证据支撑？",
        "可以把这页内容整理成适合分享的版本吗？",
    ]
    return questions[:count]


def normalize_suggested_question(value: str) -> str | None:
    text = re.sub(r"^[\s\-*>•·]*(?:\d+[\.)、]|[（(]?\d+[）)]|[A-Za-z][\.)])?\s*", "", value).strip()
    text = text.strip('"“”`')
    if not text:
        return None
    return text[:160]


def parse_suggested_questions(raw_text: str, count: int) -> list[str]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    candidates: list[str] = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed = parsed.get("questions") or parsed.get("suggested_questions") or []
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, str):
                    candidates.append(item)
                elif isinstance(item, dict):
                    question = item.get("question") or item.get("text")
                    if isinstance(question, str):
                        candidates.append(question)
    except json.JSONDecodeError:
        candidates = []
    if not candidates:
        candidates = [line for line in text.splitlines() if line.strip()]

    questions: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        question = normalize_suggested_question(candidate)
        if not question or question in seen:
            continue
        seen.add(question)
        questions.append(question)
        if len(questions) >= count:
            break
    return questions


def serialize_suggested_questions_payload(questions: Sequence[str]) -> str:
    return json.dumps({"questions": list(questions)}, ensure_ascii=False)


async def load_recent_messages(
    session: AsyncSession,
    conversation_id: str,
    limit: int = SUGGESTED_QUESTIONS_RECENT_MESSAGE_LIMIT,
) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


def build_suggested_questions_prompt(conversation: Conversation, messages: Sequence[Message], count: int) -> str:
    lines = [
        "你是 Summarix 的下一步问题推荐器。",
        f"请基于最近对话，生成 {count} 个用户下一步最值得直接点击提问的问题。",
        "要求：问题必须具体、短、可直接发送；不要解释；不要编号；只输出 JSON 字符串数组。",
        "不要重复已经问过的问题，不要编造网页中没有依据的事实。",
        "",
        "## 会话信息",
        f"- 标题：{conversation.title}",
    ]
    if conversation.page_title:
        lines.append(f"- 页面标题：{conversation.page_title}")
    if conversation.page_url:
        lines.append(f"- 页面 URL：{conversation.page_url}")
    lines.extend(["", "## 最近对话"])
    for message in messages:
        role = "用户" if message.role == "user" else "助手"
        content = message.content.replace("\n", " ").strip()
        if content:
            lines.append(f"{role}：{content[:1800]}")
    return "\n".join(lines)[:SUGGESTED_QUESTIONS_CONTEXT_LIMIT]


def extract_litellm_response_text(response: object) -> str:
    choices = getattr(response, "choices", None)
    if choices is None and isinstance(response, dict):
        choices = response.get("choices")
    if not choices:
        return ""
    choice = choices[0]
    message = getattr(choice, "message", None)
    if message is None and isinstance(choice, dict):
        message = choice.get("message")
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, list):
        return "\n".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in content)
    return str(content or "")


async def call_suggested_questions_model(prompt: str, model_config: WebAssistantModelConfig) -> str:
    from litellm import acompletion

    response = await acompletion(
        model=model_config.suggested_questions_model,
        messages=[
            {"role": "system", "content": "你只输出 JSON 字符串数组，不输出 Markdown 或解释。"},
            {"role": "user", "content": prompt},
        ],
        **build_litellm_kwargs(model_config.suggested_questions_thinking_mode),
    )
    return extract_litellm_response_text(response)


async def generate_suggested_questions(
    session: AsyncSession,
    user_id: str,
    conversation: Conversation,
    settings: Settings,
    count: int = 3,
) -> list[str]:
    if settings.chat_agent_mode == "mock":
        return build_mock_suggested_questions(count)
    model_config = await load_model_config(session, user_id, settings)
    messages = await load_recent_messages(session, conversation.id)
    prompt = build_suggested_questions_prompt(conversation, messages, count)
    raw_text = await call_suggested_questions_model(prompt, model_config)
    questions = parse_suggested_questions(raw_text, count)
    return questions or build_mock_suggested_questions(count)


async def stream_suggested_questions_for_conversation(
    session: AsyncSession,
    user_id: str,
    conversation: Conversation,
    settings: Settings,
    count: int = 3,
) -> AsyncIterator[dict[str, str]]:
    try:
        questions = await generate_suggested_questions(session, user_id, conversation, settings, count)
    except Exception:
        logger.exception("下一步建议问题生成失败，user_id=%s conversation_id=%s", user_id, conversation.id)
        questions = []
    if questions:
        yield {"event": "suggested_questions", "data": serialize_suggested_questions_payload(questions)}


async def stream_suggested_questions_response(
    session: AsyncSession,
    user_id: str,
    request: SuggestedQuestionsStreamRequest,
    settings: Settings | None = None,
) -> AsyncIterator[dict[str, str]]:
    settings = settings or get_settings()
    result = await session.execute(
        select(Conversation).where(Conversation.id == request.conversation_id, Conversation.user_id == user_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        yield {"event": "error", "data": "会话不存在或无权访问"}
        return
    async for event in stream_suggested_questions_for_conversation(
        session,
        user_id,
        conversation,
        settings,
        request.count,
    ):
        yield event
    yield {"event": "done", "data": ""}


async def stream_chat_response(
    session: AsyncSession,
    user_id: str,
    request: ChatStreamRequest,
    settings: Settings | None = None,
) -> AsyncIterator[dict[str, str]]:
    settings = settings or get_settings()
    conversation = await get_or_create_conversation(session, user_id, request, settings)
    artifacts = await load_request_artifacts(session, user_id, request.artifact_ids)
    prompt = build_prompt(request, artifacts, conversation)
    user_message = Message(conversation_id=conversation.id, role="user", content=request.message)
    session.add(user_message)
    await session.flush()
    reference_artifacts: list[MessageArtifact] = []
    if has_reference_context(request) and request.context:
        page_text = request.context.page_text[:PAGE_TEXT_PROMPT_LIMIT] if request.context.page_text else None
        reference_artifacts.append(
            await save_page_text_artifact(
                session=session,
                user_id=user_id,
                conversation_id=conversation.id,
                message_id=user_message.id,
                page_title=request.context.page_title,
                page_url=request.context.page_url,
                page_text=page_text,
                original_text_length=len(request.context.page_text) if request.context.page_text is not None else None,
                settings=settings,
            )
        )
        if request.context.page_url and not conversation.page_url:
            conversation.page_url = request.context.page_url
        if request.context.page_title and not conversation.page_title:
            conversation.page_title = request.context.page_title
    for artifact in artifacts:
        artifact.conversation_id = conversation.id
        artifact.message_id = user_message.id
    await session.commit()
    yield {
        "event": "conversation",
        "data": json.dumps(
            {
                "id": conversation.id,
                "user_message_id": user_message.id,
                "reference_artifacts": [serialize_artifact_payload(artifact) for artifact in reference_artifacts],
            },
            ensure_ascii=False,
        ),
    }

    partial_response = ""
    final_response = ""
    thought_fallback_response = ""
    adk_invocation_id: str | None = None
    try:
        if settings.chat_agent_mode == "mock":
            final_response = build_mock_response(prompt)
            yield {"event": "adk_event", "data": serialize_adk_event(mock_adk_event(final_response))}
        else:
            model_config = await load_model_config(session, user_id, settings)
            runner = create_runner(model_config, settings)
            message_parts = [types.Part.from_text(text=prompt), *await load_artifact_parts(artifacts, settings)]
            async for event in runner.run_async(
                user_id=user_id,
                session_id=conversation.adk_session_id,
                new_message=types.Content(role="user", parts=message_parts),
                run_config=RunConfig(streaming_mode=StreamingMode.SSE),
            ):
                if adk_invocation_id is None:
                    adk_invocation_id = get_event_invocation_id(event)
                event_id = getattr(event, "id", None)
                payload = {"event": "adk_event", "data": serialize_adk_event(event)}
                if event_id:
                    payload["id"] = str(event_id)
                yield payload

                visible_text, thought_text = extract_event_texts(event)
                if not visible_text and not thought_text:
                    continue
                if getattr(event, "partial", None) is True:
                    if visible_text:
                        partial_response += visible_text
                    if thought_text:
                        thought_fallback_response += thought_text
                elif is_final_response(event):
                    if visible_text:
                        final_response = merge_complete_text(partial_response or final_response, visible_text)
                    if thought_text:
                        # 某些模型会把最终可见回复错误地放进 thought part，这里做正文兜底。
                        thought_fallback_response = merge_complete_text(thought_fallback_response, thought_text)
    except Exception as error:
        logger.exception("AI 响应生成失败，user_id=%s conversation_id=%s", user_id, conversation.id)
        error_message = IMAGE_UNSUPPORTED_ERROR_MESSAGE if is_image_unsupported_error(error, artifacts) else GENERIC_STREAM_ERROR_MESSAGE
        yield {"event": "error", "data": error_message}
        return

    full_response = final_response or partial_response or thought_fallback_response
    if not full_response:
        if adk_invocation_id:
            user_message.adk_invocation_id = adk_invocation_id
            for artifact in reference_artifacts:
                artifact.adk_invocation_id = adk_invocation_id
            await session.commit()
        yield {"event": "done", "data": ""}
        return

    if adk_invocation_id:
        user_message.adk_invocation_id = adk_invocation_id
        for artifact in reference_artifacts:
            artifact.adk_invocation_id = adk_invocation_id
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=full_response,
        adk_invocation_id=adk_invocation_id,
    )
    session.add(assistant_message)
    await session.commit()
    yield {"event": "persisted", "data": json.dumps({"assistant_message_id": assistant_message.id}, ensure_ascii=False)}
    if request.suggested_questions:
        async for event in stream_suggested_questions_for_conversation(session, user_id, conversation, settings):
            yield event
    yield {"event": "done", "data": assistant_message.id}
