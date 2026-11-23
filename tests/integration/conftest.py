"""Integration-test fixtures: a freshly migrated PostgreSQL database and per-test transactions.

How to run the integration tests:

    docker compose -f compose.test.yaml up -d
    export TEST_DATABASE_URL=postgresql+asyncpg://aurorahue:aurorahue@localhost:55433/aurorahue_test
    pytest tests/integration

Without TEST_DATABASE_URL the tests are skipped. The suite drops and recreates the ``public``
schema, so it only runs against a database whose name ends with ``_test``.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from aurorahue.db.migrate import upgrade_head
from aurorahue.services.scenes import SceneService
from aurorahue.services.settings import SettingsService
from tests.support.clock import FixedClock
from tests.support.hue import FakeClient
from tests.support.services import home_bridge, light_service, session_factory

REPO_ROOT = Path(__file__).resolve().parents[2]

# bot_settings is listed too: TRUNCATE ... CASCADE empties it anyway (it references scenes);
# committed_sessions puts its one row back afterwards.
TRUNCATE_TABLES: tuple[str, ...] = ("scene_actions", "scenes", "bot_settings")


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip(
            "TEST_DATABASE_URL is not set; start compose.test.yaml and set it to run "
            "the integration tests"
        )
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        pytest.fail(
            f"Refusing to run: database {database!r} does not end with '_test'. The integration "
            "suite drops the public schema, so it only runs against a database whose name ends "
            "with '_test'."
        )
    return url


async def _reset_public_schema(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    os.environ["ALEMBIC_CONFIG"] = str(REPO_ROOT / "alembic.ini")
    asyncio.run(_reset_public_schema(database_url))
    upgrade_head(database_url)
    return database_url


@pytest.fixture
async def session(migrated_database: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            session = AsyncSession(
                bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
            )
            try:
                yield session
            finally:
                await session.close()
                await trans.rollback()
    finally:
        await engine.dispose()


# --- clock and committed sessions --------------------------------------------------------

START = datetime(2030, 1, 7, 9, 0, tzinfo=UTC)
"""Default test "now": Monday 2030-01-07 09:00 UTC."""


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


@pytest.fixture
async def committed_sessions(
    migrated_database: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Independent sessions whose commits are real, for concurrency tests.

    Do not combine with the `session` fixture. All rows in TRUNCATE_TABLES are removed afterwards.
    """
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if TRUNCATE_TABLES:
            async with engine.begin() as conn:
                await conn.execute(
                    text(f"TRUNCATE {', '.join(TRUNCATE_TABLES)} RESTART IDENTITY CASCADE")
                )
                await conn.execute(text("INSERT INTO bot_settings (id) VALUES (1)"))
        await engine.dispose()


# --- services on the test session, with a fake bridge ------------------------------------


@pytest.fixture
def fake_bridge() -> FakeClient:
    return home_bridge()


@pytest.fixture
def scenes(session: AsyncSession, fake_bridge: FakeClient, clock: FixedClock) -> SceneService:
    return SceneService(session_factory(session), light_service(fake_bridge, clock), clock)


@pytest.fixture
def settings(session: AsyncSession) -> SettingsService:
    return SettingsService(session_factory(session))
