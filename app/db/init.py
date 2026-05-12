import asyncio

from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings, get_settings
from app.db.models import Base
from app.db.session import engine


_MAINTENANCE_DATABASES = ("postgres", "template1")
_POSTGRES_IDENTIFIER_PREPARER = postgresql.dialect().identifier_preparer
_ensured_database_urls: set[str] = set()
_database_creation_locks: dict[str, asyncio.Lock] = {}


def _iter_maintenance_urls(target_url: URL) -> list[URL]:
    return [target_url.set(database=name) for name in _MAINTENANCE_DATABASES if name != target_url.database]


async def ensure_database_exists(database_url: str) -> None:
    if database_url in _ensured_database_urls:
        return

    target_url = make_url(database_url)
    if target_url.get_backend_name() != "postgresql" or not target_url.database:
        _ensured_database_urls.add(database_url)
        return

    lock = _database_creation_locks.setdefault(database_url, asyncio.Lock())
    async with lock:
        if database_url in _ensured_database_urls:
            return

        last_error: Exception | None = None
        # PostgreSQL 只能从另一个已存在的数据库连接后执行 CREATE DATABASE。
        for maintenance_url in _iter_maintenance_urls(target_url):
            admin_engine = create_async_engine(
                maintenance_url.render_as_string(hide_password=False),
                pool_pre_ping=True,
                isolation_level="AUTOCOMMIT",
            )
            try:
                async with admin_engine.connect() as connection:
                    result = await connection.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                        {"database_name": target_url.database},
                    )
                    if result.scalar_one_or_none() is None:
                        quoted_name = _POSTGRES_IDENTIFIER_PREPARER.quote(target_url.database)
                        await connection.execute(text(f"CREATE DATABASE {quoted_name}"))
                    _ensured_database_urls.add(database_url)
                    return
            except Exception as exc:
                last_error = exc
            finally:
                await admin_engine.dispose()

        if last_error is not None:
            raise last_error


async def create_all_tables(db_engine: AsyncEngine | None = None, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if db_engine is None and settings.database_auto_create_database:
        await ensure_database_exists(settings.database_url)
    target_engine = db_engine or engine
    async with target_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def drop_all_tables(db_engine: AsyncEngine | None = None) -> None:
    target_engine = db_engine or engine
    async with target_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
