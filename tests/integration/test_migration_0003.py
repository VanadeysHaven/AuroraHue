"""Migration 0003: `bot_settings.daytime_confirm`, false on the existing row (D25); up, down, up.

Synchronous on purpose: Alembic's env.py runs its own event loop via asyncio.run.
"""

import asyncio

from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from aurorahue.db.migrate import alembic_config

COLUMNS_SQL = (
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_schema = 'public' AND table_name = 'bot_settings' ORDER BY column_name"
)


def _rows(url: str, sql: str) -> list[tuple[object, ...]]:
    async def run() -> list[tuple[object, ...]]:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return [tuple(row) for row in (await conn.execute(text(sql))).all()]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_0003_up_down_up(migrated_database: str) -> None:
    cfg = alembic_config(migrated_database)
    settings_sql = "SELECT id, reset_scene_id, daytime_confirm FROM bot_settings"

    assert _rows(migrated_database, settings_sql) == [(1, None, False)]

    command.downgrade(cfg, "0002")
    assert _rows(migrated_database, COLUMNS_SQL) == [("id",), ("reset_scene_id",)]
    assert _rows(migrated_database, "SELECT version_num FROM alembic_version") == [("0002",)]

    command.upgrade(cfg, "head")  # the database is shared by the whole test session
    assert _rows(migrated_database, settings_sql) == [(1, None, False)]
