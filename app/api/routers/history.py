from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.api.schemas import ArtifactResponse, ConversationDetail, ConversationSummary, HistoryPage, MessageFeedbackPublic, MessagePublic
from app.db.models import Conversation, Message, MessageFeedback, User, utc_now
from app.db.session import get_db_session

router = APIRouter(prefix="/history", tags=["history"])


def artifact_response(artifact) -> ArtifactResponse:
    return ArtifactResponse(
        id=artifact.id,
        filename=artifact.filename,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        version=artifact.version,
        source=artifact.source,
        page_url=artifact.page_url,
        page_title=artifact.page_title,
        text_excerpt=artifact.text_excerpt,
        text_length=artifact.text_length,
        content_hash=artifact.content_hash,
        trace_id=artifact.trace_id,
        adk_invocation_id=artifact.adk_invocation_id,
    )


def feedback_response(feedback: MessageFeedback | None) -> MessageFeedbackPublic | None:
    if feedback is None:
        return None
    return MessageFeedbackPublic(
        id=feedback.id,
        rating=feedback.rating,  # type: ignore[arg-type]
        score=feedback.score,
        comment=feedback.comment,
        trace_id=feedback.trace_id,
        langwatch_sync_status=feedback.langwatch_sync_status,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


@router.get("", response_model=HistoryPage)
async def list_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> HistoryPage:
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id, Conversation.deleted_at.is_(None))
        .order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    conversations = result.scalars().all()
    return HistoryPage(
        items=[ConversationSummary.model_validate(item) for item in conversations[:limit]],
        limit=limit,
        offset=offset,
        has_more=len(conversations) > limit,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_history_detail(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationDetail:
    result = await session.execute(
        select(Conversation)
        .options(
            selectinload(Conversation.messages).selectinload(Message.artifacts),
            selectinload(Conversation.artifacts),
        )
        .where(Conversation.id == conversation_id, Conversation.user_id == current_user.id, Conversation.deleted_at.is_(None))
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    message_ids = [message.id for message in conversation.messages]
    feedback_by_message_id: dict[str, MessageFeedback] = {}
    if message_ids:
        feedback_result = await session.execute(
            select(MessageFeedback).where(MessageFeedback.user_id == current_user.id, MessageFeedback.message_id.in_(message_ids))
        )
        feedback_by_message_id = {item.message_id: item for item in feedback_result.scalars().all()}
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        page_url=conversation.page_url,
        page_title=conversation.page_title,
        updated_at=conversation.updated_at,
        messages=[
            MessagePublic(
                id=message.id,
                role=message.role,
                content=message.content,
                trace_id=message.trace_id,
                adk_invocation_id=message.adk_invocation_id,
                created_at=message.created_at,
                artifacts=[artifact_response(artifact) for artifact in message.artifacts],
                feedback=feedback_response(feedback_by_message_id.get(message.id)),
            )
            for message in conversation.messages
        ],
        artifacts=[artifact_response(artifact) for artifact in conversation.artifacts],
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_history_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    result = await session.execute(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == current_user.id, Conversation.deleted_at.is_(None))
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    conversation.deleted_at = utc_now()
    await session.commit()
