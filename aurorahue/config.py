"""Configuration loaded from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the bot."""

    token: str
    command_prefix: str = "!"
    guild_ids: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> Config:
        """Build a Config from environment variables (loading .env if present)."""
        load_dotenv()

        token = os.environ.get("DISCORD_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token."
            )

        prefix = os.environ.get("COMMAND_PREFIX", "!").strip() or "!"

        raw_guilds = os.environ.get("GUILD_IDS", "").strip()
        guild_ids = tuple(
            int(part) for part in raw_guilds.split(",") if part.strip()
        )

        return cls(token=token, command_prefix=prefix, guild_ids=guild_ids)
