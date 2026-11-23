"""The bot class and its lifecycle."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from aurorahue.config import Config
from aurorahue.core.access import LightAccess
from aurorahue.core.clock import Clock, SystemClock
from aurorahue.core.errors import BridgeUnavailable
from aurorahue.db.session import create_engine, create_sessionmaker
from aurorahue.hue.hue_client import HueClient
from aurorahue.services.lights import LightService

log = logging.getLogger(__name__)

# Cogs (extensions) loaded on startup. Add new modules here.
INITIAL_EXTENSIONS: tuple[str, ...] = ("aurorahue.cogs.general", "aurorahue.cogs.light_toggle")


class AuroraHue(commands.Bot):
    """The AuroraHue Discord bot."""

    def __init__(self, config: Config, light_access: LightAccess) -> None:
        self.config = config
        self.light_access = light_access
        self.clock: Clock = SystemClock()
        # Created in setup_hook (needs the running event loop), closed in close().
        self.db_engine: AsyncEngine | None = None
        self.sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self.hue_client: HueClient | None = None
        self.light_service: LightService | None = None

        intents = discord.Intents.default()

        super().__init__(
            command_prefix=commands.when_mentioned_or(config.command_prefix),
            intents=intents,
        )

    async def setup_hook(self) -> None:
        """Open the database pool and the bridge client, load extensions and sync commands."""
        self.db_engine = create_engine(self.config.database_url)
        self.sessionmaker = create_sessionmaker(self.db_engine)
        self.hue_client = HueClient(self.config.hue_bridge_ip, self.config.hue_app_key)
        self.light_service = LightService(self.hue_client, self.light_access, self.clock)
        await self._check_bridge()

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

    async def _check_bridge(self) -> None:
        """Warn about access-file IDs the bridge doesn't know (D3). An unreachable bridge doesn't
        stop the bot (D5); commands report it instead."""
        assert self.light_service is not None
        try:
            unknown = await self.light_service.unknown_access_ids()
        except BridgeUnavailable:
            log.warning(
                "Can't reach the Hue bridge at startup; light commands fail until it's back"
            )
            return
        for light_id in unknown:
            log.warning(
                "%s lists light %s, which isn't on the bridge", self.config.lights_config, light_id
            )

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id: %s)", self.user, getattr(self.user, "id", "?"))

    async def close(self) -> None:
        """Gracefully log out from Discord and close the database pool on shutdown.

        Invoked by discord.py's signal handlers (SIGINT/SIGTERM) and on any
        other shutdown path. Delegating to ``super().close()`` closes the
        websocket and HTTP session so the bot logs out cleanly.
        """
        log.info("Shutting down: logging out from Discord")
        await super().close()
        log.info("Logged out from Discord")
        if self.hue_client is not None:
            await self.hue_client.aclose()
        if self.db_engine is not None:
            await self.db_engine.dispose()
            log.info("Closed database connections")


def run(config: Config, light_access: LightAccess) -> None:
    """Create and run the bot until it disconnects."""
    bot = AuroraHue(config, light_access)
    bot.run(config.token, log_handler=None)
