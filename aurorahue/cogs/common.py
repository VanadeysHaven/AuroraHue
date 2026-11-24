"""Shared Discord pieces: the user check, the daytime confirmation (D21, D25), the `lights` and
`scene` options (D6, §7), reply text for light changes (D22) and the one app-command error
handler."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, cast

import discord
from discord import app_commands

from aurorahue.core.errors import AuroraHueError, BridgeUnavailable
from aurorahue.helpers import sun_finder
from aurorahue.services.lights import ApplyReport, LightService, Outcome
from aurorahue.services.scenes import SceneService
from aurorahue.services.settings import SettingsService

if TYPE_CHECKING:
    from aurorahue.bot import AuroraHue

log = logging.getLogger(__name__)

NO_MENTIONS = discord.AllowedMentions.none()
NOT_ALLOWED_MESSAGE = "You are not allowed to use this command."
UNEXPECTED_MESSAGE = "Something went wrong; it has been logged."
LIGHTS_DESCRIPTION = "Light names, comma-separated (empty = all lights)"

# D21 reads the bridge before the interaction is answered; Discord allows 3 seconds for that.
FRESH_READ_TIMEOUT = 2.0
CONFIRM_TIMEOUT = 60


def bot_of(interaction: discord.Interaction) -> AuroraHue:
    return cast("AuroraHue", interaction.client)


def light_service(interaction: discord.Interaction) -> LightService:
    service = bot_of(interaction).light_service
    assert service is not None, "set up in AuroraHue.setup_hook"
    return service


def scene_service(interaction: discord.Interaction) -> SceneService:
    service = bot_of(interaction).scene_service
    assert service is not None, "set up in AuroraHue.setup_hook"
    return service


def settings_service(interaction: discord.Interaction) -> SettingsService:
    service = bot_of(interaction).settings_service
    assert service is not None, "set up in AuroraHue.setup_hook"
    return service


def escape(text: str) -> str:
    """User-visible text from outside the bot (light and scene names): no markdown, no pings."""
    return discord.utils.escape_mentions(discord.utils.escape_markdown(text))


def is_allowed() -> Callable[[app_commands.T], app_commands.T]:
    """Allow the command only for user IDs in `ALLOWED_USER_IDS`; empty = everyone (D20)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        allowed = bot_of(interaction).config.allowed_user_ids
        if allowed and interaction.user.id not in allowed:
            raise app_commands.CheckFailure(NOT_ALLOWED_MESSAGE)
        return True

    return app_commands.check(predicate)


class ConfirmView(discord.ui.View):
    """Go ahead / Cancel, only for the user who ran the command. `value` stays None on timeout.

    `confirm_label` and `confirm_text` relabel the button and its "working on it" text
    (`/scene delete`: "Delete", "Deleting…").
    """

    def __init__(
        self, caller_id: int, *, confirm_label: str = "Go ahead", confirm_text: str = "Going ahead…"
    ) -> None:
        super().__init__(timeout=CONFIRM_TIMEOUT)
        self.caller_id = caller_id
        self.value: bool | None = None
        self.confirm.label = confirm_label
        self._confirm_text = confirm_text

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.caller_id

    @discord.ui.button(label="Go ahead", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.value = True
        await interaction.response.edit_message(content=self._confirm_text, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.value = False
        await interaction.response.edit_message(content="Cancelled; nothing changed.", view=None)
        self.stop()


async def confirm_if_daytime(
    interaction: discord.Interaction, switching_on: Collection[str]
) -> bool:
    """D21: when the daytime confirmation is on (D25) and it's daytime, ask before switching on a
    light (ID in `switching_on`) that is off right now (fresh bridge read). Returns whether to go
    ahead.

    Call it before answering the interaction. When it returns True the interaction is answered
    (the ephemeral question, or a public defer), so send the result with `interaction.followup`;
    a follow-up after the question is a new, public message (D22).
    """
    bot = bot_of(interaction)
    if (
        switching_on
        and (await settings_service(interaction).get_settings()).daytime_confirm
        and sun_finder.is_daytime(bot.config)
    ):
        try:
            async with asyncio.timeout(FRESH_READ_TIMEOUT):
                lights = await light_service(interaction).allowed(fresh=True)
        except TimeoutError:
            raise BridgeUnavailable() from None
        wanted = set(switching_on)
        if any(not light.on for light in lights if light.id in wanted):
            view = ConfirmView(interaction.user.id)
            sun_phase = sun_finder.get_sun_phase_message(bot.config)
            await interaction.response.send_message(
                f"It's daytime - {sun_phase} Turn the lights on?",
                view=view,
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            await view.wait()
            if view.value is None:
                await interaction.edit_original_response(
                    content="No answer; nothing changed.", view=None
                )
            return bool(view.value)
    await interaction.response.defer(thinking=True)
    return True


async def lights_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """D6: allowed light names; after a comma, `"<already picked>, <next>"`."""
    try:
        allowed = await light_service(interaction).allowed()
    except BridgeUnavailable:
        return []
    *picked_parts, typed = current.split(",")
    picked = [part.strip() for part in picked_parts if part.strip()]
    taken = {name.casefold() for name in picked}
    typed = typed.strip().casefold()
    prefix = ", ".join(picked)

    names = dict.fromkeys(light.name for light in allowed)
    candidates = [n for n in names if n.casefold() not in taken and typed in n.casefold()]
    candidates.sort(key=lambda name: not name.casefold().startswith(typed))  # prefix hits first

    choices: list[app_commands.Choice[str]] = []
    for name in candidates:
        value = f"{prefix}, {name}" if prefix else name
        if len(value) > 100:  # Discord's limit for choice names and values
            continue
        choices.append(app_commands.Choice(name=value, value=value))
        if len(choices) == 25:
            break
    return choices


def lights_option[T](func: T) -> T:
    """The optional `lights` option: description + autocomplete (D6)."""
    func = app_commands.describe(lights=LIGHTS_DESCRIPTION)(func)
    return app_commands.autocomplete(lights=lights_autocomplete)(func)


async def scene_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Scene names containing what's typed (any case), prefix hits first, at most 25 (§7)."""
    scenes = await scene_service(interaction).list_scenes()
    return [
        app_commands.Choice(name=name, value=name)
        for name in match_names([scene.name for scene in scenes], current)
    ]


def match_names(names: list[str], typed: str, limit: int = 25) -> list[str]:
    """`names` containing `typed` (any case), those starting with it first, at most `limit`."""
    needle = typed.strip().casefold()
    hits = [name for name in names if needle in name.casefold()]
    hits.sort(key=lambda name: not name.casefold().startswith(needle))  # stable: keeps order
    return hits[:limit]


def _join(names: list[str]) -> str:
    return ", ".join(escape(name) for name in names)


def report_text(report: ApplyReport, verb: str, suffix: str = "") -> str:
    """D22 reply for a light change: "Turned on 3 lights. Colour skipped for: Hallway.
    Didn't answer: Desk." `verb` and `suffix` frame the lights: "Set" … " to #ff8800"."""
    changed = report.names(Outcome.OK, Outcome.COLOR_SKIPPED)
    if not changed:
        parts = ["No lights changed."]
    elif len(changed) == 1:
        parts = [f"{verb} {escape(changed[0])}{suffix}."]
    else:
        parts = [f"{verb} {len(changed)} lights{suffix}."]

    if skipped := report.names(Outcome.COLOR_SKIPPED):
        parts.append(f"Colour skipped for: {_join(skipped)}.")
    if failed := report.names(Outcome.FAILED):
        parts.append(f"Didn't answer: {_join(failed)}.")
    if not_allowed := report.names(Outcome.NOT_ALLOWED):
        parts.append(f"Not controllable any more: {_join(not_allowed)}.")
    if missing := len(report.names(Outcome.MISSING)):
        verb_form = "isn't" if missing == 1 else "aren't"
        plural = "" if missing == 1 else "s"
        parts.append(f"{missing} light{plural} {verb_form} on the bridge any more.")
    return " ".join(parts)


def error_text(error: Exception) -> str | None:
    """The user-facing message for an app-command error, or None when it's unexpected.

    `AuroraHueError` messages can quote user text (`No light named "x".`), so they're escaped.
    """
    if isinstance(error, app_commands.CommandInvokeError):
        error = error.original
    if isinstance(error, app_commands.CheckFailure):
        return NOT_ALLOWED_MESSAGE
    if isinstance(error, AuroraHueError):
        return escape(error.message)
    return None


async def send_ephemeral(interaction: discord.Interaction, text: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=NO_MENTIONS)
    else:
        await interaction.response.send_message(text, ephemeral=True, allowed_mentions=NO_MENTIONS)


async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    """The one handler (`tree.error`): user errors ephemerally, everything else logged."""
    text = error_text(error)
    if text is None:
        command = interaction.command.qualified_name if interaction.command else "?"
        log.error("Command /%s failed", command, exc_info=error)
        text = UNEXPECTED_MESSAGE
    try:
        await send_ephemeral(interaction, text)
    except discord.HTTPException:
        log.warning("Couldn't send the error message for an interaction", exc_info=True)
