"""Entry point: ``python main.py`` (and the ``aurorahue`` console script)."""

from __future__ import annotations

import logging

from aurorahue.bot import run
from aurorahue.config import Config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    config = Config.from_env()
    run(config)


if __name__ == "__main__":
    main()
