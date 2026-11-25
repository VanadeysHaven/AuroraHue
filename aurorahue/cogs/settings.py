"""`/settings`: show or change the bot's settings (D18): the reset scene (D19), the daytime
confirmation (D25, D26) and the lights a bare /on leaves alone (D31, D32, D34)."""

from collections.abc import Mapping

import discord
from discord import app_commands
from discord.ext import commands

from aurorahue.cogs.common import (
    NO_MENTIONS,
    escape,
    is_allowed,
    light_service,
    lights_autocomplete,
    match_names,
    scene_service,
    settings_service,
)
from aurorahue.core.errors import BridgeUnavailable
from aurorahue.services.lights import LightService
from aurorahue.services.settings import SettingsView

NONE_CHOICE = "none"
ON = "on"
OFF = "off"


def settings_text(view: SettingsView, light_names: Mapping[str, str] | None) -> str:
    """D26: every setting, one line each. `light_names` maps allowed light IDs to names (None:
    the bridge didn't answer); excluded IDs that aren't in it are counted, not named (D34)."""
    if view.reset_scene_name is None:
        scene = "none"
    else:
        scene = f"**{escape(view.reset_scene_name)}**"
    confirm = ON if view.daytime_confirm else OFF
    excluded = excluded_text(view.on_exclude, light_names)
    return f"Reset scene: {scene}\nDaytime confirmation: {confirm}\nExcluded from /on: {excluded}"


def excluded_text(excluded: tuple[str, ...], light_names: Mapping[str, str] | None) -> str:
    """D34: "Desk, Hallway (+1 not controllable)", "none", or a count when the bridge is down."""
    if not excluded:
        return "none"
    if light_names is None:
        plural = "" if len(excluded) == 1 else "s"
        return f"{len(excluded)} light{plural} (bridge unreachable)"
    names = sorted((light_names[i] for i in excluded if i in light_names), key=str.casefold)
    text = ", ".join(escape(name) for name in names) or "none"
    if hidden := sum(1 for i in excluded if i not in light_names):
        text += f" (+{hidden} not controllable)"
    return text


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


async def on_exclude_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """D32: "none" first when it fits what's typed, then the D6 light names (25 at most)."""
    choices: list[app_commands.Choice[str]] = []
    if "," not in current and current.strip().casefold() in NONE_CHOICE:
        choices.append(app_commands.Choice(name=NONE_CHOICE, value=NONE_CHOICE))
    choices.extend(await lights_autocomplete(interaction, current))
    return choices[:25]


class Settings(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="settings", description="Show or change the bot's settings.")
    @app_commands.describe(
        reset_scene="A scene for /reset, or none to clear it",
        daytime_confirm="Ask before switching lights on in daytime",
        on_exclude="Lights /on without lights leaves alone (comma-separated, or none)",
    )
    @app_commands.rename(
        reset_scene="reset-scene", daytime_confirm="daytime-confirm", on_exclude="on-exclude"
    )
    @app_commands.autocomplete(
        reset_scene=reset_scene_autocomplete, on_exclude=on_exclude_autocomplete
    )
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
        on_exclude: str | None = None,
    ) -> None:
        service = settings_service(interaction)
        lights = light_service(interaction)
        # D32: resolve the light names before writing anything, so a bad name changes nothing.
        exclude_ids: list[str] | None = None
        if on_exclude is not None and on_exclude.replace(",", " ").strip():
            if on_exclude.strip().casefold() == NONE_CHOICE:
                exclude_ids = []
            else:
                exclude_ids = [light.id for light in await lights.resolve(on_exclude)]

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
        names = await _light_names(lights)
        if exclude_ids is not None:
            view = await service.set_on_exclude(exclude_ids)
            if exclude_ids:
                left_out = excluded_text(view.on_exclude, names)
                changes.append(f"/on without lights now leaves out: {left_out}.")
            else:
                changes.append("/on without lights switches every light on.")
        current = settings_text(await service.get_settings(), names)
        text = "\n".join(changes) + "\n\n" + current if changes else current
        await interaction.response.send_message(text, ephemeral=True, allowed_mentions=NO_MENTIONS)


async def _light_names(lights: LightService) -> dict[str, str] | None:
    """Allowed light IDs -> names (the cached list), or None when the bridge doesn't answer."""
    try:
        return {light.id: light.name for light in await lights.allowed()}
    except BridgeUnavailable:
        return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Settings(bot))
