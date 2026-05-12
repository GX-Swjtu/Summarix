import pytest

from app.core.config import Settings
from app.db import init as db_init


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