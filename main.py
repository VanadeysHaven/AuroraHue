"""Entry point: ``python main.py`` runs the bot, ``python main.py lights`` lists the bridge's lights
(also as the ``aurorahue`` console script)."""

from __future__ import annotations

import argparse
import asyncio
import logging

from aurorahue.config import Config, ConfigError, HueSettings, load_light_access
from aurorahue.core.errors import BridgeUnavailable

log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="AuroraHue, a Discord bot for Philips Hue.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["lights"],
        help="lights: list every light on the bridge with its UUID, then exit",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    try:
        if args.command == "lights":
            raise SystemExit(_lights())
        _run_bot()
    except ConfigError as exc:
        # D3: a broken access file stops the bot with a readable message, no traceback.
        log.critical("%s", exc)
        raise SystemExit(1) from None


def _lights() -> int:
    from aurorahue.cli import print_lights

    try:
        return asyncio.run(print_lights(HueSettings.from_env()))
    except BridgeUnavailable as exc:
        log.error("%s", exc.message)
        return 1


def _run_bot() -> None:
    # Imported here so `main.py lights` doesn't load discord.py or the database code.
    from aurorahue.bot import run
    from aurorahue.db.migrate import upgrade_head

    config = Config.from_env()
    light_access = load_light_access(config.lights_config)
    if config.run_migrations:
        # Before bot.run: Alembic's env.py calls asyncio.run, which can't run inside the bot's loop.
        log.info("Running database migrations")
        upgrade_head(config.database_url)
    run(config, light_access)


if __name__ == "__main__":
    main()
