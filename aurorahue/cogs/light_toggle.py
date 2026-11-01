import discord
from discord import app_commands
from discord.ext import commands

from aurorahue.helpers import sun_finder
from aurorahue.hue.hue_client import (
    HueClient,
    MINIMUM_BRIGHTNESS,
    ON_EXCLUDED_LIGHT_IDS,
    SOFT_BRIGHTNESS,
)


def is_allowed():
    """Allow the command only for user IDs in config.allowed_user_ids.

    An empty allowlist means everyone is allowed.
    """

    async def predicate(interaction: discord.Interaction) -> bool:
        allowed = interaction.client.config.allowed_user_ids
        if allowed and interaction.user.id not in allowed:
            raise app_commands.CheckFailure("You are not allowed to use this command.")
        return True

    return app_commands.check(predicate)


class ConfirmView(discord.ui.View):
    def __init__(self, caller_id: int):
        super().__init__(timeout=60)
        self.caller_id = caller_id
        self.value: bool | None = None

    async def interaction_check(self, interaction):
        return interaction.user.id == self.caller_id

    @discord.ui.button(label="Turn on anyway", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.edit_message(content="Turning on...", view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.edit_message(content="Cancelled.", view=None)
        self.stop()


class LightToggle(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.config = bot.config
        self.hue_client = HueClient(bridge_ip=self.config.hue_bridge_ip, app_key=self.config.hue_app_key)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            message = "You are not allowed to use this command."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return
        raise error

    async def _turn_on_gated(
        self, interaction: discord.Interaction, brightness: float | None, done_message: str
    ) -> None:
        """Turn lights on, asking for confirmation first if it's daytime."""
        await interaction.response.defer(ephemeral=True)

        if sun_finder.is_daytime(self.config):
            view = ConfirmView(interaction.user.id)
            await interaction.followup.send(
                f"It's daytime - {sun_finder.get_sun_phase_message(self.config)} Turn the lights on?",
                view=view, ephemeral=True,
            )
            await view.wait()
            if not view.value:
                return

        await self.hue_client.set_all_lights(
            on=True, exclude=ON_EXCLUDED_LIGHT_IDS, brightness=brightness
        )
        await interaction.followup.send(done_message)

    @app_commands.command(name="on", description="Turn all lights on.")
    @is_allowed()
    async def lights_on(self, interaction: discord.Interaction):
        await self._turn_on_gated(interaction, None, "Turned lights on!")

    @app_commands.command(name="minimum", description="Turn all lights on at minimum brightness.")
    @is_allowed()
    async def lights_minimum(self, interaction: discord.Interaction):
        await self._turn_on_gated(interaction, MINIMUM_BRIGHTNESS, "Set lights to minimum brightness!")

    @app_commands.command(name="soft", description="Turn all lights on at half brightness.")
    @is_allowed()
    async def lights_soft(self, interaction: discord.Interaction):
        await self._turn_on_gated(interaction, SOFT_BRIGHTNESS, "Set lights to soft brightness!")

    @app_commands.command(name="off", description="Turn all lights off.")
    @is_allowed()
    async def lights_off(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.hue_client.set_all_lights(on=False)
        await interaction.followup.send("Turned lights off!")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LightToggle(bot))
