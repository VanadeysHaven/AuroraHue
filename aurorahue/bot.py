"""The bot class and its lifecycle."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .config import Config

log = logging.getLogger(__name__)

# Cogs (extensions) loaded on startup. Add new modules here.
INITIAL_EXTENSIONS: tuple[str, ...] = ("aurorahue.cogs.general", "aurorahue.cogs.light_toggle")


class AuroraHue(commands.Bot):
    """The AuroraHue Discord bot."""

    def __init__(self, config: Config) -> None:
        self.config = config

        intents = discord.Intents.default()

        super().__init__(
            command_prefix=commands.when_mentioned_or(config.command_prefix),
            intents=intents,
        )

    async def setup_hook(self) -> None:
        """Load extensions and sync application (slash) commands."""
        for extension in INITIAL_EXTENSIONS:
            await self.load_extension(extension)
            log.info("Loaded extension %s", extension)

        if self.config.guild_ids:
            for guild_id in self.config.guild_ids:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("Synced commands to guild %s", guild_id)
        else:
            await self.tree.sync()
            log.info("Synced commands globally")

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id: %s)", self.user, getattr(self.user, "id", "?"))

    async def close(self) -> None:
        """Gracefully log out from Discord on shutdown.

        Invoked by discord.py's signal handlers (SIGINT/SIGTERM) and on any
        other shutdown path. Delegating to ``super().close()`` closes the
        websocket and HTTP session so the bot logs out cleanly.
        """
        log.info("Shutting down: logging out from Discord")
        await super().close()
        log.info("Logged out from Discord")


def run(config: Config) -> None:
    """Create and run the bot until it disconnects."""
    bot = AuroraHue(config)
    bot.run(config.token, log_handler=None)
