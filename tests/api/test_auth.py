import pytest
from httpx import AsyncClient

from app.core.config import Settings


def test_settings_reject_weak_jwt_secret():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(jwt_secret_key="change-me-in-.env")


@pytest.mark.parametrize(
    "pattern",
    [
        r"^(chrome-extension|moz-extension)://.*$",
        r"^chrome-extension://[a-z]+$",
        r"^(https://localhost:5173|chrome-extension://[a-z]+)$",
    ],
)
def test_settings_reject_extension_cors_regex(pattern: str):
    with pytest.raises(ValueError, match="BROWSER_EXTENSION_ORIGINS"):
        Settings(
            jwt_secret_key="x" * 32,
            cors_allow_origin_regex=pattern,
        )


def test_settings_allow_http_cors_regex():
    settings = Settings(
        jwt_secret_key="x" * 32,
        cors_allow_origin_regex=r"^https://(localhost|127\\.0\\.0\\.1)(:\\d+)?$",
    )
    assert settings.cors_allow_origin_regex == r"^https://(localhost|127\\.0\\.0\\.1)(:\\d+)?$"


@pytest.mark.asyncio
async def test_register_login_refresh_and_logout(client: AsyncClient):
    register_response = await client.post(
        "/api/auth/register",
        json={"email": "user@example.com", "password": "StrongPass123"},
    )
    assert register_response.status_code == 201
    assert register_response.json()["user"]["email"] == "user@example.com"
    assert "summarix_access" in client.cookies
    assert "summarix_refresh" in client.cookies
    cookies = register_response.headers.get_list("set-cookie")
    assert any("summarix_access=" in item and "Path=/" in item for item in cookies)
    assert any("summarix_refresh=" in item and "Path=/api/auth" in item for item in cookies)

    logout_response = await client.post("/api/auth/logout")
    assert logout_response.status_code == 204
    logout_cookies = logout_response.headers.get_list("set-cookie")
    assert any("summarix_refresh=" in item and "Path=/api/auth" in item and "SameSite=lax" in item for item in logout_cookies)

    login_response = await client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "StrongPass123"},
    )
    assert login_response.status_code == 200

    refresh_response = await client.post("/api/auth/refresh")
    assert refresh_response.status_code == 200
    assert refresh_response.json()["user"]["email"] == "user@example.com"

    me_response = await client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["user"]["email"] == "user@example.com"
