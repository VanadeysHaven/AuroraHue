"""`/settings`: show or change the bot's settings (D18): the reset scene (D19) and the daytime
confirmation (D25, D26)."""

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
from aurorahue.services.settings import SettingsView

NONE_CHOICE = "none"
ON = "on"
OFF = "off"


def settings_text(view: SettingsView) -> str:
    """D26: every setting, one line each."""
    if view.reset_scene_name is None:
        scene = "none"
    else:
        scene = f"**{escape(view.reset_scene_name)}**"
    confirm = ON if view.daytime_confirm else OFF
    return f"Reset scene: {scene}\nDaytime confirmation: {confirm}"


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
    @app_commands.describe(
        reset_scene="A scene for /reset, or none to clear it",
        daytime_confirm="Ask before switching lights on in daytime",
    )
    @app_commands.rename(reset_scene="reset-scene", daytime_confirm="daytime-confirm")
    @app_commands.autocomplete(reset_scene=reset_scene_autocomplete)
    @app_commands.choices(
        daytime_confirm=[
            app_commands.Choice(name=ON, value=ON),
            app_commands.Choice(name=OFF, value=OFF),
        ]
    )
    @is_allowed()
    async def settings(
        self,
        interaction: discord.Interaction,
        reset_scene: str | None = None,
        daytime_confirm: app_commands.Choice[str] | None = None,
    ) -> None:
        service = settings_service(interaction)
        changes: list[str] = []
        if reset_scene is not None:
            if reset_scene.strip().casefold() == NONE_CHOICE:
                await service.set_reset_scene(None)
                changes.append("Reset scene cleared; `/reset` does nothing until you pick one.")
            else:
                found = await scene_service(interaction).get(reset_scene)
                await service.set_reset_scene(found.id)
                changes.append("Reset scene set; `/reset` runs it.")
        if daytime_confirm is not None:
            enabled = daytime_confirm.value == ON
            await service.set_daytime_confirm(enabled)
            if enabled:
                changes.append(
                    "Daytime confirmation on; switching an off light on in daytime asks first."
                )
            else:
                changes.append("Daytime confirmation off; light commands never ask.")
        current = settings_text(await service.get_settings())
        text = "\n".join(changes) + "\n\n" + current if changes else current
        await interaction.response.send_message(text, ephemeral=True, allowed_mentions=NO_MENTIONS)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Settings(bot))
