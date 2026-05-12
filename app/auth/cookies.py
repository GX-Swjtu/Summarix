from datetime import timedelta

from fastapi import Response

from app.core.config import Settings, get_settings


def set_auth_cookies(response: Response, access_token: str, refresh_token: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    response.set_cookie(
        settings.access_cookie_name,
        access_token,
        max_age=int(timedelta(minutes=settings.access_token_minutes).total_seconds()),
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        domain=settings.auth_cookie_domain,
        path="/",
    )
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        max_age=int(timedelta(days=settings.refresh_token_days).total_seconds()),
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        domain=settings.auth_cookie_domain,
        path=settings.effective_refresh_cookie_path,
    )


def clear_auth_cookies(response: Response, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    response.delete_cookie(
        settings.access_cookie_name,
        domain=settings.auth_cookie_domain,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
    response.delete_cookie(
        settings.refresh_cookie_name,
        domain=settings.auth_cookie_domain,
        path=settings.effective_refresh_cookie_path,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
