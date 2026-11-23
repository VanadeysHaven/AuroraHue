"""Direct light commands: /on, /off, /color, /brightness (D7, D8) and /lights (D23)."""

import discord
from discord import app_commands
from discord.ext import commands

from aurorahue.cogs.common import (
    NO_MENTIONS,
    confirm_if_daytime,
    escape,
    is_allowed,
    light_service,
    lights_option,
    report_text,
)
from aurorahue.core.color import mirek_to_kelvin, parse_brightness, parse_color, xy_to_hex
from aurorahue.hue.hue_client import BridgeLight
from aurorahue.services.lights import LightRequest


class Lights(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="on", description="Switch lights on, keeping their colour.")
    @lights_option
    @is_allowed()
    async def on(self, interaction: discord.Interaction, lights: str | None = None) -> None:
        service = light_service(interaction)
        ids = [light.id for light in await service.resolve(lights)]
        if not await confirm_if_daytime(interaction, ids):
            return
        report = await service.apply(ids, LightRequest(on=True))
        await interaction.followup.send(
            report_text(report, "Turned on"), allowed_mentions=NO_MENTIONS
        )

    @app_commands.command(name="off", description="Switch lights off.")
    @lights_option
    @is_allowed()
    async def off(self, interaction: discord.Interaction, lights: str | None = None) -> None:
        service = light_service(interaction)
        ids = [light.id for light in await service.resolve(lights)]
        await interaction.response.defer(thinking=True)
        report = await service.apply(ids, LightRequest(on=False))
        await interaction.followup.send(
            report_text(report, "Turned off"), allowed_mentions=NO_MENTIONS
        )

    @app_commands.command(name="color", description="Set a colour and switch the lights on.")
    @app_commands.describe(color="Hex like #ff8800 or white temperature like 2700K")
    @lights_option
    @is_allowed()
    async def color(
        self, interaction: discord.Interaction, color: str, lights: str | None = None
    ) -> None:
        wanted = parse_color(color)
        service = light_service(interaction)
        ids = [light.id for light in await service.resolve(lights)]
        if not await confirm_if_daytime(interaction, ids):
            return
        report = await service.apply(ids, LightRequest(on=True, color=wanted))
        await interaction.followup.send(
            report_text(report, "Set", f" to {wanted}"), allowed_mentions=NO_MENTIONS
        )

    @app_commands.command(
        name="brightness", description="Set the brightness and switch the lights on."
    )
    @app_commands.describe(percent="0-100; 0 is the lowest glow, not off")
    @lights_option
    @is_allowed()
    async def brightness(
        self,
        interaction: discord.Interaction,
        percent: app_commands.Range[int, 0, 100],
        lights: str | None = None,
    ) -> None:
        level = parse_brightness(percent)
        service = light_service(interaction)
        ids = [light.id for light in await service.resolve(lights)]
        if not await confirm_if_daytime(interaction, ids):
            return
        report = await service.apply(ids, LightRequest(on=True, brightness=level))
        await interaction.followup.send(
            report_text(report, "Set", f" to {level}% brightness"), allowed_mentions=NO_MENTIONS
        )

    @app_commands.command(name="lights", description="Show the lights the bot controls.")
    @is_allowed()
    async def lights(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        allowed = await light_service(interaction).allowed(fresh=True)
        text = "\n".join(_light_line(light) for light in allowed) or "No lights to control."
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=NO_MENTIONS)


def _light_line(light: BridgeLight) -> str:
    """D23: "**Desk** — on, 40%, 2700K" (temperature mode) or the nearest hex."""
    name = f"**{escape(light.name)}**"
    if not light.on:
        return f"{name} — off"
    parts = ["on"]
    if light.brightness is not None:
        parts.append(f"{round(light.brightness)}%")
    if light.mirek is not None:
        parts.append(f"{mirek_to_kelvin(light.mirek)}K")
    elif light.xy is not None and light.xy[1] > 0:
        parts.append(xy_to_hex(*light.xy))
    return f"{name} — {', '.join(parts)}"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Lights(bot))
