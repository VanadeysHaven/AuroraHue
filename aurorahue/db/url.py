"""The database URL on its own, so Alembic runs without the rest of the bot config."""

from __future__ import annotations

import os

from dotenv import load_dotenv


def database_url() -> str:
    """``DATABASE_URL`` from the environment (loading .env if present)."""
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy the database lines from .env.example into .env."
        )
    return url
