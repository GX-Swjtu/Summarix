from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import Base
from app.db.session import engine


async def create_all_tables(db_engine: AsyncEngine | None = None) -> None:
    target_engine = db_engine or engine
    async with target_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def drop_all_tables(db_engine: AsyncEngine | None = None) -> None:
    target_engine = db_engine or engine
    async with target_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
