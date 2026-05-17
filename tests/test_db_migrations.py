import pytest
from sqlalchemy import inspect, text

from app.db.init import downgrade_database, drop_all_tables, upgrade_database
from app.db.session import engine


EXPECTED_TABLES = {
    "users",
    "refresh_tokens",
    "conversations",
    "messages",
    "message_artifacts",
    "user_model_preferences",
    "message_feedback",
}
HEAD_REVISION = "202605180001"


async def get_table_names() -> set[str]:
    async with engine.connect() as connection:
        return await connection.run_sync(lambda sync_connection: set(inspect(sync_connection).get_table_names()))


@pytest.mark.asyncio
async def test_upgrade_database_creates_current_schema_from_empty_database():
    await drop_all_tables(engine)
    await upgrade_database(engine)

    table_names = await get_table_names()
    async with engine.connect() as connection:
        revision = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()

    assert EXPECTED_TABLES.issubset(table_names)
    assert revision == HEAD_REVISION


@pytest.mark.asyncio
async def test_downgrade_database_removes_application_tables():
    await downgrade_database(engine, revision="base")

    table_names = await get_table_names()

    assert EXPECTED_TABLES.isdisjoint(table_names)