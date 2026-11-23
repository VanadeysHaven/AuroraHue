"""ORM models. Every table is registered on `Base.metadata` by importing this module."""

from aurorahue.db.base import Base  # noqa: F401  # re-exported for migrations/env.py

# Tables arrive in segment 4 (scenes, settings).
