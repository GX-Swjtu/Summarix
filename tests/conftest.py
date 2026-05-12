import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["DATABASE_AUTO_CREATE_DATABASE"] = "false"
os.environ["DATABASE_AUTO_CREATE_TABLES"] = "false"
os.environ["JWT_SECRET_KEY"] = "test-secret-with-at-least-thirty-two-bytes"
os.environ["CHAT_AGENT_MODE"] = "mock"
os.environ["CHAT_ARTIFACT_ROOT"] = ".data/test-artifacts"

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.core.config import get_settings
from app.db.init import create_all_tables, drop_all_tables
from app.db.session import engine


@pytest_asyncio.fixture(autouse=True)
async def reset_database():
    await drop_all_tables(engine)
    await create_all_tables(engine)
    yield


@pytest_asyncio.fixture
async def client():
    get_settings.cache_clear()
    app = create_app(get_settings())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest_asyncio.fixture
async def authenticated_client(client: AsyncClient) -> AsyncClient:
    response = await client.post(
        "/api/auth/register",
        json={"email": "tester@example.com", "password": "StrongPass123"},
    )
    assert response.status_code == 201
    return client
