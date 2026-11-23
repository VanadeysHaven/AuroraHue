"""Entry point: ``python main.py`` (and the ``aurorahue`` console script)."""

from __future__ import annotations

import logging

from aurorahue.bot import run
from aurorahue.config import Config
from aurorahue.db.migrate import upgrade_head

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    config = Config.from_env()
    if config.run_migrations:
        # Before bot.run: Alembic's env.py calls asyncio.run, which can't run inside the bot's loop.
        log.info("Running database migrations")
        upgrade_head(config.database_url)
    run(config)


if __name__ == "__main__":
    main()
