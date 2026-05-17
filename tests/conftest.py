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
os.environ["DEFAULT_CHAT_MODEL"] = "dashscope/qwen3.5-flash"
os.environ["LOG_FORMAT"] = "text"
os.environ["LOG_LEVEL"] = "INFO"
for model_env_name in (
    "MODEL_CATALOG_FILE",
    "MODEL_CATALOG_JSON",
    "DEFAULT_PRIMARY_MODEL_ID",
    "SUGGESTED_QUESTIONS_MODEL_ID",
    "TEXT_SUMMARY_MODEL",
    "CONVERSATION_MODEL",
    "XIAOHONGSHU_MODEL",
    "SHORT_VIDEO_SCRIPT_MODEL",
    "SUGGESTED_QUESTIONS_MODEL",
):
    os.environ[model_env_name] = ""
os.environ["TEXT_SUMMARY_THINKING_MODE"] = "default"
os.environ["CONVERSATION_THINKING_MODE"] = "default"
os.environ["XIAOHONGSHU_THINKING_MODE"] = "default"
os.environ["SHORT_VIDEO_SCRIPT_THINKING_MODE"] = "default"
os.environ["SUGGESTED_QUESTIONS_THINKING_MODE"] = "disabled"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.core.config import get_settings
from app.db.init import drop_all_tables, upgrade_database
from app.db.session import engine


@pytest.fixture(autouse=True)
def reset_langwatch_initialized():
    """每个测试前后重置 LangWatch 全局单例，防止跨测试状态泄漏。"""
    import app.monitoring.langwatch as lw_module
    lw_module._langwatch_initialized = False
    yield
    lw_module._langwatch_initialized = False


@pytest_asyncio.fixture(autouse=True)
async def reset_database():
    await drop_all_tables(engine)
    await upgrade_database(engine)
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
