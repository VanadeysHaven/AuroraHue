import discord
from discord import app_commands
from discord.ext import commands

from aurorahue.hue.hue_client import HueClient

class LightToggle(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        config = bot.config
        self.hue_client = HueClient(bridge_ip=config.hue_bridge_ip, app_key=config.hue_app_key)

    @app_commands.command(name="on", description="Turn all lights on.")
    async def lights_on(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.hue_client.set_all_lights(on=True)
        await interaction.followup.send("Turned lights on!")

    @app_commands.command(name="off", description="Turn all lights off.")
    async def lights_off(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.hue_client.set_all_lights(on=False)
        await interaction.followup.send("Turned lights off!")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LightToggle(bot))
    