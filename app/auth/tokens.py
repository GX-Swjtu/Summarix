from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.core.config import Settings, get_settings


TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    pass


def hash_token_id(token_id: str) -> str:
    return hashlib.sha256(token_id.encode("utf-8")).hexdigest()


def create_token(user_id: str, token_type: TokenType, expires_delta: timedelta, settings: Settings | None = None) -> tuple[str, str, datetime]:
    settings = settings or get_settings()
    token_id = str(uuid.uuid4())
    expires_at = datetime.now(UTC) + expires_delta
    payload = {
        "sub": user_id,
        "typ": token_type,
        "jti": token_id,
        "iat": datetime.now(UTC),
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, token_id, expires_at


def decode_token(token: str, expected_type: TokenType, settings: Settings | None = None) -> dict[str, str]:
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError("无效或已过期的登录凭证") from exc
    if payload.get("typ") != expected_type:
        raise TokenError("登录凭证类型不匹配")
    user_id = payload.get("sub")
    token_id = payload.get("jti")
    if not user_id or not token_id:
        raise TokenError("登录凭证缺少必要字段")
    return {"user_id": str(user_id), "token_id": str(token_id)}
