"""Shared pieces of the database services: the data model base and the session factory type."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

type SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
"""Opens a session per call: the bot passes its `async_sessionmaker`; tests wrap the test
session. Services commit their own work."""


class StrictModel(BaseModel):
    """Immutable, no type coercion: a wrong type is a bug and fails loudly (like Sidequest).

    Keyword arguments only (pydantic models take no positional arguments).
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
