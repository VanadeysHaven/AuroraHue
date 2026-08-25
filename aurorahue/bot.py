"""The bot class and its lifecycle."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .config import Config

log = logging.getLogger(__name__)

# Cogs (extensions) loaded on startup. Add new modules here.
INITIAL_EXTENSIONS: tuple[str, ...] = ("aurorahue.cogs.general",)


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


def run(config: Config) -> None:
    """Create and run the bot until it disconnects."""
    bot = AuroraHue(config)
    bot.run(config.token, log_handler=None)
