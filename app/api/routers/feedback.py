from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import FeedbackRequest, FeedbackResponse
from app.core.config import Settings, get_settings
from app.db.models import Conversation, Message, MessageFeedback, User
from app.db.session import get_db_session
from app.monitoring.feedback import create_langwatch_annotation
from app.monitoring.metrics import record_feedback


router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    payload: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> FeedbackResponse:
    result = await session.execute(
        select(Message, Conversation)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Message.id == payload.message_id, Conversation.user_id == current_user.id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在")
    message, conversation = row
    if message.role != "assistant":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能评价助手回复")

    trace_id = payload.trace_id or message.trace_id or message.adk_invocation_id
    score = 1 if payload.rating == "like" else -1
    existing_result = await session.execute(
        select(MessageFeedback).where(MessageFeedback.user_id == current_user.id, MessageFeedback.message_id == message.id)
    )
    feedback = existing_result.scalar_one_or_none()
    if feedback is None:
        feedback = MessageFeedback(
            user_id=current_user.id,
            conversation_id=conversation.id,
            message_id=message.id,
            trace_id=trace_id,
            adk_invocation_id=message.adk_invocation_id,
            rating=payload.rating,
            score=score,
            comment=payload.comment,
            source=payload.source,
        )
        session.add(feedback)
        try:
            await session.flush()
        except IntegrityError:
            # 并发请求已先完成插入；回滚后改为更新已有记录。
            await session.rollback()
            re_result = await session.execute(
                select(MessageFeedback).where(
                    MessageFeedback.user_id == current_user.id,
                    MessageFeedback.message_id == message.id,
                )
            )
            feedback = re_result.scalar_one()
    # 统一更新所有可变字段（兼容新建成功和并发冲突改为更新两条路径）
    feedback.trace_id = trace_id
    feedback.adk_invocation_id = message.adk_invocation_id
    feedback.rating = payload.rating
    feedback.score = score
    feedback.comment = payload.comment
    feedback.source = payload.source

    annotation = await create_langwatch_annotation(
        settings,
        trace_id=trace_id,
        is_thumbs_up=payload.rating == "like",
        comment=payload.comment,
        email=current_user.email,
    )
    feedback.langwatch_sync_status = annotation.status
    feedback.langwatch_annotation_id = annotation.annotation_id
    feedback.langwatch_sync_error = annotation.error
    await session.commit()
    await session.refresh(feedback)
    record_feedback(payload.rating, annotation.status)
    return FeedbackResponse(
        id=feedback.id,
        message_id=feedback.message_id,
        rating=feedback.rating,  # type: ignore[arg-type]
        score=feedback.score,
        trace_id=feedback.trace_id,
        langwatch_synced=annotation.synced,
        langwatch_sync_status=feedback.langwatch_sync_status,
        langwatch_annotation_id=feedback.langwatch_annotation_id,
        langwatch_sync_error=feedback.langwatch_sync_error,
    )