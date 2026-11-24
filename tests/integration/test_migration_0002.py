"""Migration 0002: scenes, scene_actions, bot_settings (with its one row); up, down, up.

Synchronous on purpose: Alembic's env.py runs its own event loop via asyncio.run.
"""

import asyncio

from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from aurorahue.db.migrate import alembic_config

TABLES = {"scenes", "scene_actions", "bot_settings"}


def _rows(url: str, sql: str) -> list[tuple[object, ...]]:
    async def run() -> list[tuple[object, ...]]:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return [tuple(row) for row in (await conn.execute(text(sql))).all()]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _tables(url: str) -> set[str]:
    rows = _rows(url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    return {str(name) for (name,) in rows} & TABLES


def test_0002_up_down_up(migrated_database: str) -> None:
    cfg = alembic_config(migrated_database)

    assert _tables(migrated_database) == TABLES
    assert _rows(migrated_database, "SELECT id, reset_scene_id FROM bot_settings") == [(1, None)]

    command.downgrade(cfg, "0001")
    assert _tables(migrated_database) == set()
    assert _rows(migrated_database, "SELECT version_num FROM alembic_version") == [("0001",)]

    command.upgrade(cfg, "head")  # the database is shared by the whole test session
    assert _tables(migrated_database) == TABLES
    assert _rows(migrated_database, "SELECT id, reset_scene_id FROM bot_settings") == [(1, None)]
