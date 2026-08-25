"""General-purpose commands. A starting point to copy from."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class General(commands.Cog):
    """Basic commands available to everyone."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check that the bot is responsive.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong! ({latency_ms}ms)")


async def setup(bot: commands.Bot) -> None:
    """discord.py extension entry point."""
    await bot.add_cog(General(bot))
