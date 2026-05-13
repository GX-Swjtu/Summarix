from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.api.schemas import ArtifactResponse, ConversationDetail, ConversationSummary, HistoryPage, MessagePublic
from app.db.models import Conversation, Message, User
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
        adk_invocation_id=artifact.adk_invocation_id,
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
        .where(Conversation.user_id == current_user.id)
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
        .where(Conversation.id == conversation_id, Conversation.user_id == current_user.id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
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
                adk_invocation_id=message.adk_invocation_id,
                created_at=message.created_at,
                artifacts=[artifact_response(artifact) for artifact in message.artifacts],
            )
            for message in conversation.messages
        ],
        artifacts=[artifact_response(artifact) for artifact in conversation.artifacts],
    )
