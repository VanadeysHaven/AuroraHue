"""`/settings`: show or change the bot's settings, for now the reset scene (D18)."""

import discord
from discord import app_commands
from discord.ext import commands

from aurorahue.cogs.common import (
    NO_MENTIONS,
    escape,
    is_allowed,
    match_names,
    scene_service,
    settings_service,
)

NONE_CHOICE = "none"


async def reset_scene_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """D18: "none" first when it fits what's typed, then matching scene names (25 at most)."""
    choices: list[app_commands.Choice[str]] = []
    if current.strip().casefold() in NONE_CHOICE:
        choices.append(app_commands.Choice(name=NONE_CHOICE, value=NONE_CHOICE))
    names = [scene.name for scene in await scene_service(interaction).list_scenes()]
    for name in match_names(names, current, limit=24):
        choices.append(app_commands.Choice(name=name, value=name))
    return choices


class Settings(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="settings", description="Show or change the bot's settings.")
    @app_commands.describe(reset_scene="A scene for /reset, or none to clear it")
    @app_commands.rename(reset_scene="reset-scene")
    @app_commands.autocomplete(reset_scene=reset_scene_autocomplete)
    @is_allowed()
    async def settings(
        self, interaction: discord.Interaction, reset_scene: str | None = None
    ) -> None:
        if reset_scene is None:
            current = await settings_service(interaction).get_settings()
            if current.reset_scene_name is None:
                text = "Reset scene: none"
            else:
                text = f"Reset scene: **{escape(current.reset_scene_name)}**"
        elif reset_scene.strip().casefold() == NONE_CHOICE:
            await settings_service(interaction).set_reset_scene(None)
            text = "Reset scene cleared; `/reset` does nothing until you pick one."
        else:
            found = await scene_service(interaction).get(reset_scene)
            await settings_service(interaction).set_reset_scene(found.id)
            text = f"Reset scene: **{escape(found.name)}**. `/reset` runs it."
        await interaction.response.send_message(text, ephemeral=True, allowed_mentions=NO_MENTIONS)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Settings(bot))
