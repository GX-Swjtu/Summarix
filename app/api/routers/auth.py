from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import AuthResponse, LoginRequest, RegisterRequest, UserPublic
from app.auth.cookies import clear_auth_cookies, set_auth_cookies
from app.auth.service import AuthError, authenticate_user, issue_token_pair, register_user, revoke_refresh_token, rotate_refresh_token
from app.auth.tokens import TokenError, decode_token
from app.core.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    try:
        user = await register_user(session, payload.email, payload.password)
        access_token, refresh_token, _ = await issue_token_pair(session, user, request.headers.get("user-agent"), settings)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    set_auth_cookies(response, access_token, refresh_token, settings)
    return AuthResponse(user=UserPublic.model_validate(user))


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    try:
        user = await authenticate_user(session, payload.email, payload.password)
        access_token, refresh_token, _ = await issue_token_pair(session, user, request.headers.get("user-agent"), settings)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    set_auth_cookies(response, access_token, refresh_token, settings)
    return AuthResponse(user=UserPublic.model_validate(user))


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少刷新凭证")
    try:
        payload = decode_token(refresh_token, "refresh", settings)
        user = await session.get(User, payload["user_id"])
        if user is None or not user.is_active:
            raise AuthError("用户不存在或已停用")
        access_token, new_refresh_token = await rotate_refresh_token(
            session, user, payload["token_id"], request.headers.get("user-agent"), settings
        )
    except (TokenError, AuthError) as exc:
        clear_auth_cookies(response, settings)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    set_auth_cookies(response, access_token, new_refresh_token, settings)
    return AuthResponse(user=UserPublic.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if refresh_token:
        try:
            payload = decode_token(refresh_token, "refresh", settings)
            await revoke_refresh_token(session, payload["user_id"], payload["token_id"])
        except TokenError:
            pass
    clear_auth_cookies(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=AuthResponse)
async def me(current_user: User = Depends(get_current_user)) -> AuthResponse:
    return AuthResponse(user=UserPublic.model_validate(current_user))
