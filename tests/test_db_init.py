import pytest
from sqlalchemy import select

from app.auth.passwords import verify_password
from app.core.config import Settings
from app.db import init as db_init
from app.db.models import User
from app.db.session import AsyncSessionLocal


@pytest.fixture(autouse=True)
def clear_database_init_cache():
    db_init._ensured_database_urls.clear()
    db_init._database_creation_locks.clear()


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeConnection:
    def __init__(self, exists: bool):
        self.exists = exists
        self.executed: list[tuple[str, dict[str, str] | None]] = []

    async def execute(self, statement, parameters=None):
        sql = str(statement).strip()
        self.executed.append((sql, parameters))
        if sql.startswith("SELECT 1 FROM pg_database"):
            return FakeResult(1 if self.exists else None)
        return FakeResult(None)


class FakeConnectContext:
    def __init__(self, connection: FakeConnection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeAdminEngine:
    def __init__(self, connection: FakeConnection):
        self.connection = connection
        self.disposed = False

    def connect(self):
        return FakeConnectContext(self.connection)

    async def dispose(self):
        self.disposed = True


class FakeBeginConnection:
    def __init__(self):
        self.called_with = None

    async def run_sync(self, function):
        self.called_with = function


class FakeBeginContext:
    def __init__(self, connection: FakeBeginConnection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeMetadataEngine:
    def __init__(self, connection: FakeBeginConnection):
        self.connection = connection

    def begin(self):
        return FakeBeginContext(self.connection)


class FakeTargetEngine:
    def __init__(self):
        self.disposed = False

    async def dispose(self):
        self.disposed = True


@pytest.mark.asyncio
async def test_ensure_database_exists_skips_sqlite(monkeypatch: pytest.MonkeyPatch):
    def fail_create_async_engine(*args, **kwargs):
        raise AssertionError("sqlite 不应触发建库引擎")

    monkeypatch.setattr(db_init, "create_async_engine", fail_create_async_engine)

    await db_init.ensure_database_exists("sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_ensure_database_exists_creates_missing_postgres_database(monkeypatch: pytest.MonkeyPatch):
    connection = FakeConnection(exists=False)
    admin_engine = FakeAdminEngine(connection)
    created_urls: list[tuple[str, dict[str, object]]] = []

    def fake_create_async_engine(url: str, **kwargs):
        created_urls.append((url, kwargs))
        return admin_engine

    monkeypatch.setattr(db_init, "create_async_engine", fake_create_async_engine)

    await db_init.ensure_database_exists("postgresql+asyncpg://tester:secret@db.example.com:5432/summarix-dev")

    assert created_urls == [
        (
            "postgresql+asyncpg://tester:secret@db.example.com:5432/postgres",
            {"pool_pre_ping": True, "isolation_level": "AUTOCOMMIT"},
        )
    ]
    assert connection.executed == [
        ("SELECT 1 FROM pg_database WHERE datname = :database_name", {"database_name": "summarix-dev"}),
        ('CREATE DATABASE "summarix-dev"', None),
    ]
    assert admin_engine.disposed is True


@pytest.mark.asyncio
async def test_create_all_tables_ensures_database_before_creating_metadata(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, object]] = []
    metadata_connection = FakeBeginConnection()

    async def fake_ensure_database_exists(database_url: str):
        calls.append(("db", database_url))

    monkeypatch.setattr(db_init, "ensure_database_exists", fake_ensure_database_exists)
    monkeypatch.setattr(db_init, "engine", FakeMetadataEngine(metadata_connection))

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="postgresql+asyncpg://tester:secret@db.example.com:5432/summarix",
        database_auto_create_database=True,
    )

    await db_init.create_all_tables(settings=settings)

    assert calls == [("db", settings.database_url)]
    assert metadata_connection.called_with is not None


@pytest.mark.asyncio
async def test_reset_database_recreates_postgres_database(monkeypatch: pytest.MonkeyPatch):
    connection = FakeConnection(exists=True)
    admin_engine = FakeAdminEngine(connection)
    target_engine = FakeTargetEngine()
    created_urls: list[tuple[str, dict[str, object]]] = []

    def fake_create_async_engine(url: str, **kwargs):
        created_urls.append((url, kwargs))
        return admin_engine

    monkeypatch.setattr(db_init, "create_async_engine", fake_create_async_engine)

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="postgresql+asyncpg://tester:secret@db.example.com:5432/summarix-dev",
        database_auto_create_database=True,
    )

    await db_init.reset_database(db_engine=target_engine, settings=settings)

    assert target_engine.disposed is True
    assert created_urls == [
        (
            "postgresql+asyncpg://tester:secret@db.example.com:5432/postgres",
            {"pool_pre_ping": True, "isolation_level": "AUTOCOMMIT"},
        )
    ]
    assert connection.executed == [
        (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :database_name AND pid <> pg_backend_pid()",
            {"database_name": "summarix-dev"},
        ),
        ('DROP DATABASE IF EXISTS "summarix-dev"', None),
        ('CREATE DATABASE "summarix-dev"', None),
    ]
    assert settings.database_url in db_init._ensured_database_urls


@pytest.mark.asyncio
async def test_ensure_admin_user_upserts_expected_credentials():
    first_user = await db_init.ensure_admin_user(admin_email="ADMIN@admin.com", admin_password="OldPass123")
    updated_user = await db_init.ensure_admin_user(admin_email="admin@admin.com", admin_password="adminGaoxin")

    assert updated_user.id == first_user.id
    assert updated_user.email == "admin@admin.com"
    assert verify_password("adminGaoxin", updated_user.password_hash)

    async with AsyncSessionLocal() as session:
        stored_user = (await session.execute(select(User).where(User.email == "admin@admin.com"))).scalar_one()
        assert stored_user.is_active is True
        assert verify_password("adminGaoxin", stored_user.password_hash)


@pytest.mark.asyncio
async def test_rebuild_database_with_admin_calls_reset_create_and_seed(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str | None, str | None]] = []

    async def fake_reset_database(db_engine=None, settings=None):
        calls.append(("reset", None, None))

    async def fake_create_all_tables(db_engine=None, settings=None):
        calls.append(("create", None, None))

    async def fake_ensure_admin_user(admin_email: str, admin_password: str, session_factory=None):
        calls.append(("admin", admin_email, admin_password))
        return User(email=admin_email, password_hash="hashed")

    monkeypatch.setattr(db_init, "reset_database", fake_reset_database)
    monkeypatch.setattr(db_init, "create_all_tables", fake_create_all_tables)
    monkeypatch.setattr(db_init, "ensure_admin_user", fake_ensure_admin_user)

    user = await db_init.rebuild_database_with_admin(
        admin_email="admin@admin.com",
        admin_password="adminGaoxin",
    )

    assert user.email == "admin@admin.com"
    assert calls == [
        ("reset", None, None),
        ("create", None, None),
        ("admin", "admin@admin.com", "adminGaoxin"),
    ]