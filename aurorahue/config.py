"""Configuration loaded from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the bot."""

    token: str

    hue_app_key: str
    hue_bridge_ip: str

    command_prefix: str = "!"
    guild_ids: tuple[int, ...] = field(default_factory=tuple)
    allowed_user_ids: tuple[int, ...] = field(default_factory=tuple)

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

        raw_allowed = os.environ.get("ALLOWED_USER_IDS", "").strip()
        allowed_user_ids = tuple(
            int(part) for part in raw_allowed.split(",") if part.strip()
        )

        hue_app_key = os.environ.get("HUE_APP_KEY", "").strip()
        hue_bridge_ip = os.environ.get("HUE_BRIDGE_IP", "").strip()

        return cls(token=token, command_prefix=prefix, guild_ids=guild_ids, allowed_user_ids=allowed_user_ids, hue_app_key=hue_app_key, hue_bridge_ip=hue_bridge_ip)
