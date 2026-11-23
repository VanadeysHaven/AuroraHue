"""Configuration loaded from the environment."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from aurorahue.core.access import LightAccess
from aurorahue.db.url import database_url as _database_url

log = logging.getLogger(__name__)

DEFAULT_LIGHTS_CONFIG = Path("configs/lights.json")

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


class ConfigError(Exception):
    """A configuration file or setting the bot can't start with. The message is shown as is."""


@dataclass(frozen=True)
class HueSettings:
    """What talking to the bridge needs; no Discord token (used by `python main.py lights`)."""

    bridge_ip: str
    app_key: str
    lights_config: Path

    @classmethod
    def from_env(cls) -> HueSettings:
        load_dotenv()
        raw_path = os.environ.get("LIGHTS_CONFIG", "").strip()
        return cls(
            bridge_ip=os.environ.get("HUE_BRIDGE_IP", "").strip(),
            app_key=os.environ.get("HUE_APP_KEY", "").strip(),
            lights_config=Path(raw_path) if raw_path else DEFAULT_LIGHTS_CONFIG,
        )


def load_light_access(path: Path) -> LightAccess:
    """Read and validate the light access file (D1-D3).

    No file -> every light allowed, with a warning. A file that can't be read or doesn't validate
    -> `ConfigError` listing each problem as `<field>: <pydantic message>`.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.warning("No light access file at %s: the bot may control every light", path)
        log.info("Light access: all lights (no file)")
        return LightAccess(whitelist=False)
    except OSError as exc:
        raise ConfigError(f"Can't read the light access file {path}: {exc}") from exc

    try:
        access = LightAccess.model_validate_json(text)
    except ValidationError as exc:
        problems = "\n".join(
            f"  {'.'.join(str(part) for part in error['loc']) or '(file)'}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigError(f"The light access file {path} is invalid:\n{problems}") from exc

    log.info("Light access: %s", access.describe())
    return access


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
    # The light access file (D1), read once at startup by `load_light_access`.
    lights_config: Path = DEFAULT_LIGHTS_CONFIG

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

        hue = HueSettings.from_env()

        latitude = float(os.environ.get("LATITUDE", "0") or "0")
        longitude = float(os.environ.get("LONGITUDE", "0") or "0")

        run_migrations = _env_bool("RUN_MIGRATIONS", default=True)

        return cls(
            token=token,
            command_prefix=prefix,
            guild_ids=guild_ids,
            allowed_user_ids=allowed_user_ids,
            hue_app_key=hue.app_key,
            hue_bridge_ip=hue.bridge_ip,
            latitude=latitude,
            longitude=longitude,
            database_url=_database_url(),
            run_migrations=run_migrations,
            lights_config=hue.lights_config,
        )
