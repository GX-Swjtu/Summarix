import argparse
import asyncio
from pathlib import Path
from urllib.parse import unquote

from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.passwords import hash_password
from app.core.config import Settings, get_settings
from app.db.models import Base, User
from app.db.session import AsyncSessionLocal, engine


_MAINTENANCE_DATABASES = ("postgres", "template1")
_POSTGRES_IDENTIFIER_PREPARER = postgresql.dialect().identifier_preparer
_ensured_database_urls: set[str] = set()
_database_creation_locks: dict[str, asyncio.Lock] = {}
DEFAULT_ADMIN_EMAIL = "admin@admin.com"
DEFAULT_ADMIN_PASSWORD = "adminGaoxin"


def _iter_maintenance_urls(target_url: URL) -> list[URL]:
    return [target_url.set(database=name) for name in _MAINTENANCE_DATABASES if name != target_url.database]


def _resolve_sqlite_database_path(target_url: URL) -> Path | None:
    database = unquote(target_url.database or "")
    if not database or database == ":memory:":
        return None
    if database.startswith("/") and len(database) >= 3 and database[2] == ":":
        database = database.lstrip("/")
    return Path(database)


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


async def reset_database(db_engine: AsyncEngine | None = None, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    target_engine = db_engine or engine
    await target_engine.dispose()

    database_url = settings.database_url
    target_url = make_url(database_url)
    _ensured_database_urls.discard(database_url)
    _database_creation_locks.pop(database_url, None)

    if target_url.get_backend_name() == "postgresql" and target_url.database:
        last_error: Exception | None = None
        # 删除数据库前先断开其他连接，否则 PostgreSQL 会拒绝 DROP DATABASE。
        for maintenance_url in _iter_maintenance_urls(target_url):
            admin_engine = create_async_engine(
                maintenance_url.render_as_string(hide_password=False),
                pool_pre_ping=True,
                isolation_level="AUTOCOMMIT",
            )
            try:
                async with admin_engine.connect() as connection:
                    quoted_name = _POSTGRES_IDENTIFIER_PREPARER.quote(target_url.database)
                    await connection.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) "
                            "FROM pg_stat_activity "
                            "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                        ),
                        {"database_name": target_url.database},
                    )
                    await connection.execute(text(f"DROP DATABASE IF EXISTS {quoted_name}"))
                    await connection.execute(text(f"CREATE DATABASE {quoted_name}"))
                    _ensured_database_urls.add(database_url)
                    return
            except Exception as exc:
                last_error = exc
            finally:
                await admin_engine.dispose()

        if last_error is not None:
            raise last_error
        return

    if target_url.get_backend_name() == "sqlite":
        sqlite_path = _resolve_sqlite_database_path(target_url)
        if sqlite_path is not None and sqlite_path.exists():
            sqlite_path.unlink()
        _ensured_database_urls.add(database_url)
        return

    raise ValueError("当前只支持 PostgreSQL 或 SQLite 的整库重建")


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


async def ensure_admin_user(
    admin_email: str = DEFAULT_ADMIN_EMAIL,
    admin_password: str = DEFAULT_ADMIN_PASSWORD,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> User:
    normalized_email = admin_email.strip().lower()
    target_session_factory = session_factory or AsyncSessionLocal

    async with target_session_factory() as session:
        result = await session.execute(select(User).where(User.email == normalized_email))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(email=normalized_email, password_hash=hash_password(admin_password), is_active=True)
            session.add(user)
        else:
            user.password_hash = hash_password(admin_password)
            user.is_active = True
        await session.commit()
        await session.refresh(user)
        return user


async def rebuild_database_with_admin(
    admin_email: str = DEFAULT_ADMIN_EMAIL,
    admin_password: str = DEFAULT_ADMIN_PASSWORD,
    db_engine: AsyncEngine | None = None,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> User:
    settings = settings or get_settings()
    await reset_database(db_engine=db_engine, settings=settings)
    await create_all_tables(db_engine=db_engine, settings=settings)
    return await ensure_admin_user(
        admin_email=admin_email,
        admin_password=admin_password,
        session_factory=session_factory,
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="开发环境数据库初始化工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reset_parser = subparsers.add_parser("reset", help="删除库、重建库并初始化管理员账号")
    reset_parser.add_argument("--admin-email", default=DEFAULT_ADMIN_EMAIL, help="管理员邮箱")
    reset_parser.add_argument("--admin-password", default=DEFAULT_ADMIN_PASSWORD, help="管理员密码")
    return parser


async def run_cli() -> None:
    args = build_cli_parser().parse_args()
    if args.command == "reset":
        user = await rebuild_database_with_admin(
            admin_email=args.admin_email,
            admin_password=args.admin_password,
        )
        print(f"数据库已重建，管理员账号已初始化：{user.email}")


def main() -> None:
    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
