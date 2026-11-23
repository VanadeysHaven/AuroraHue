"""Configuration loaded from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .db.url import database_url as _database_url

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise RuntimeError(f"{name} must be true or false, got {raw!r}.")


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the bot."""

    token: str

    hue_app_key: str
    hue_bridge_ip: str

    latitude: float
    longitude: float

    database_url: str

    command_prefix: str = "!"
    guild_ids: tuple[int, ...] = field(default_factory=tuple)
    allowed_user_ids: tuple[int, ...] = field(default_factory=tuple)

    # Run "alembic upgrade head" before the bot starts.
    run_migrations: bool = True
    # The light access file (read in segment 2).
    lights_config: Path = Path("configs/lights.json")

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
        guild_ids = tuple(int(part) for part in raw_guilds.split(",") if part.strip())

        raw_allowed = os.environ.get("ALLOWED_USER_IDS", "").strip()
        allowed_user_ids = tuple(int(part) for part in raw_allowed.split(",") if part.strip())

        hue_app_key = os.environ.get("HUE_APP_KEY", "").strip()
        hue_bridge_ip = os.environ.get("HUE_BRIDGE_IP", "").strip()

        latitude = float(os.environ.get("LATITUDE", "0") or "0")
        longitude = float(os.environ.get("LONGITUDE", "0") or "0")

        run_migrations = _env_bool("RUN_MIGRATIONS", default=True)
        lights_config = Path(os.environ.get("LIGHTS_CONFIG", "").strip() or "configs/lights.json")

        return cls(
            token=token,
            command_prefix=prefix,
            guild_ids=guild_ids,
            allowed_user_ids=allowed_user_ids,
            hue_app_key=hue_app_key,
            hue_bridge_ip=hue_bridge_ip,
            latitude=latitude,
            longitude=longitude,
            database_url=_database_url(),
            run_migrations=run_migrations,
            lights_config=lights_config,
        )
