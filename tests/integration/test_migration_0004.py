"""Migration 0004: `bot_settings.on_exclude`, empty on the existing row (D31); up, down, up.

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
SETTINGS_SQL = "SELECT id, on_exclude FROM bot_settings"


def _rows(url: str, sql: str) -> list[tuple[object, ...]]:
    async def run() -> list[tuple[object, ...]]:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return [tuple(row) for row in (await conn.execute(text(sql))).all()]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_0004_up_down_up(migrated_database: str) -> None:
    cfg = alembic_config(migrated_database)

    assert _rows(migrated_database, SETTINGS_SQL) == [(1, [])]

    command.downgrade(cfg, "0003")
    assert _rows(migrated_database, COLUMNS_SQL) == [
        ("daytime_confirm",),
        ("id",),
        ("reset_scene_id",),
    ]
    assert _rows(migrated_database, "SELECT version_num FROM alembic_version") == [("0003",)]

    command.upgrade(cfg, "head")  # the database is shared by the whole test session
    assert _rows(migrated_database, SETTINGS_SQL) == [(1, [])]
