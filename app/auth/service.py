from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password, verify_password
from app.auth.tokens import create_token, hash_token_id
from app.core.config import Settings, get_settings
from app.db.models import RefreshToken, User


class AuthError(Exception):
    pass


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def register_user(session: AsyncSession, email: str, password: str) -> User:
    if await get_user_by_email(session, email):
        raise AuthError("邮箱已被注册")
    user = User(email=email.lower(), password_hash=hash_password(password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(session, email)
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthError("邮箱或密码错误")
    return user


async def issue_token_pair(session: AsyncSession, user: User, user_agent: str | None, settings: Settings | None = None) -> tuple[str, str, RefreshToken]:
    settings = settings or get_settings()
    access_token, _, _ = create_token(user.id, "access", timedelta(minutes=settings.access_token_minutes), settings)
    refresh_token, refresh_id, refresh_expires_at = create_token(user.id, "refresh", timedelta(days=settings.refresh_token_days), settings)
    stored_refresh = RefreshToken(
        user_id=user.id,
        token_hash=hash_token_id(refresh_id),
        expires_at=refresh_expires_at,
        user_agent=user_agent,
    )
    session.add(stored_refresh)
    await session.commit()
    return access_token, refresh_token, stored_refresh


async def rotate_refresh_token(session: AsyncSession, user: User, refresh_token_id: str, user_agent: str | None, settings: Settings | None = None) -> tuple[str, str]:
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.token_hash == hash_token_id(refresh_token_id),
            RefreshToken.revoked_at.is_(None),
        )
    )
    stored_refresh = result.scalar_one_or_none()
    if stored_refresh is None or as_utc(stored_refresh.expires_at) <= datetime.now(UTC):
        raise AuthError("刷新凭证已失效")
    stored_refresh.revoked_at = datetime.now(UTC)
    access_token, refresh_token, _ = await issue_token_pair(session, user, user_agent, settings)
    await session.commit()
    return access_token, refresh_token


async def revoke_refresh_token(session: AsyncSession, user_id: str, refresh_token_id: str) -> None:
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.token_hash == hash_token_id(refresh_token_id),
            RefreshToken.revoked_at.is_(None),
        )
    )
    stored_refresh = result.scalar_one_or_none()
    if stored_refresh is not None:
        stored_refresh.revoked_at = datetime.now(UTC)
        await session.commit()
