"""The scene builder (D16): an in-memory editor for one scene's actions, saved in one go.

An ephemeral embed with one line per light in the scene, a **Set lights…** select (pick lights →
a form with state, colour and brightness), a **Remove lights…** select, **Save** and **Cancel**.
Only the user who opened it can use it; it expires after 14.5 minutes, before Discord's
interaction token (15 minutes) would stop it from editing its own message.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

import discord

from aurorahue.cogs.common import (
    NO_MENTIONS,
    UNEXPECTED_MESSAGE,
    error_text,
    escape,
    send_ephemeral,
)
from aurorahue.core.color import parse_brightness, parse_color
from aurorahue.core.errors import InvalidInput
from aurorahue.hue.hue_client import BridgeLight
from aurorahue.services.scenes import ActionInput, SceneInput, SceneService

log = logging.getLogger(__name__)

BUILDER_TIMEOUT = 14.5 * 60
EXPIRED_MESSAGE = "This scene editor expired; nothing was saved."
NOT_OWNER_MESSAGE = "Only the person who opened this scene editor can use it."
SELECT_LIMIT = 25  # Discord's maximum options per select
MODAL_TITLE_MAX = 45


# --- Rendering (pure; tests/unit/test_scene_render.py) -------------------------------------


def action_summary(action: ActionInput) -> str:
    """ "on, #ff8800, 40%" / "on, 40%" / "on" / "off" (D13: empty fields keep the light's value)."""
    if not action.on:
        return "off"
    parts = ["on"]
    if action.color is not None:
        parts.append(action.color)
    if action.brightness is not None:
        parts.append(f"{action.brightness}%")
    return ", ".join(parts)


def action_line(name: str, action: ActionInput) -> str:
    """ "**Desk** — on, #ff8800, 40%"; `name` is escaped here."""
    return f"**{escape(name)}** — {action_summary(action)}"


def builder_lines(actions: Mapping[str, ActionInput], names: Mapping[str, str]) -> list[str]:
    """One line per light in the scene, sorted by light name (any case)."""
    ordered = sorted(actions, key=lambda light_id: names[light_id].casefold())
    return [action_line(names[light_id], actions[light_id]) for light_id in ordered]


def parse_action(light_id: str, state: str, color: str, brightness: str) -> ActionInput:
    """The form's three fields → one action (D9, D10, D13). Raises `InvalidInput`."""
    on = state == "on"
    color = color.strip()
    brightness = brightness.strip()
    if not on and (color or brightness):
        raise InvalidInput("A light that's switched off takes no colour or brightness.")
    level: int | None = None
    if brightness:
        if not brightness.isdecimal():
            raise InvalidInput("Brightness is a whole number from 0 to 100.")
        level = parse_brightness(int(brightness))
    return ActionInput(
        light_id=light_id,
        on=on,
        color=str(parse_color(color)) if color else None,
        brightness=level,
    )


# --- The view -------------------------------------------------------------------------------


class SceneBuilder(discord.ui.View):
    """Holds the scene being built; nothing reaches the database before Save."""

    def __init__(
        self,
        *,
        owner_id: int,
        scenes: SceneService,
        lights: Sequence[BridgeLight],
        name: str,
        scene_id: int | None = None,
        old_name: str | None = None,
        actions: Sequence[ActionInput] = (),
    ) -> None:
        super().__init__(timeout=BUILDER_TIMEOUT)
        self.owner_id = owner_id
        self.scenes = scenes
        self.name = name
        self.scene_id = scene_id
        self.old_name = old_name
        # Only allowed lights can be picked or shown (D4).
        self.names = {light.id: light.name for light in lights}
        self.actions = {a.light_id: a for a in actions if a.light_id in self.names}
        # Saving needs every light allowed (brief §6), so actions for lights that are no longer
        # allowed (or gone) are dropped here, and the embed says so without naming them (D4).
        self.dropped = sum(1 for a in actions if a.light_id not in self.names)
        self.origin: discord.Interaction | None = None
        self._rebuild()

    # -- rendering

    def embed(self) -> discord.Embed:
        if self.scene_id is None:
            title = f"New scene: {self.name}"
        elif self.old_name is not None and self.old_name != self.name:
            title = f"Editing scene: {self.old_name} → {self.name}"
        else:
            title = f"Editing scene: {self.name}"
        lines = builder_lines(self.actions, self.names) or [
            "No lights yet. Pick some with **Set lights…**."
        ]
        if self.dropped:
            plural = "light" if self.dropped == 1 else "lights"
            lines += ["", f"*Left out {self.dropped} {plural} the bot can't control any more.*"]
        embed = discord.Embed(title=escape(title)[:256], description="\n".join(lines))
        embed.set_footer(
            text="Lights not in the scene are left alone. Nothing is saved until Save."
        )
        return embed

    def _rebuild(self) -> None:
        """Re-create the two selects so their options match the current actions."""
        self.clear_items()
        self.add_item(_SetLightsSelect(self))
        self.add_item(_RemoveLightsSelect(self))
        self.add_item(self.save)
        self.add_item(self.cancel)

    async def refresh(self, interaction: discord.Interaction) -> None:
        """Show the current state on the builder message (answers `interaction`)."""
        self._rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    def shared_action(self, light_ids: Sequence[str]) -> ActionInput | None:
        """The action all `light_ids` share, if they're all in the scene with the same values."""
        found = {self.actions.get(light_id) for light_id in light_ids}
        if len(found) != 1 or None in found:
            return None
        action = found.pop()
        assert action is not None
        return action

    # -- lifecycle

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await send_ephemeral(interaction, NOT_OWNER_MESSAGE)
            return False
        return True

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        await _show_error(interaction, error)

    async def on_timeout(self) -> None:
        if self.origin is None:
            return
        try:
            await self.origin.edit_original_response(
                content=EXPIRED_MESSAGE, embed=None, view=None, allowed_mentions=NO_MENTIONS
            )
        except discord.HTTPException:
            log.info("Couldn't mark an expired scene editor", exc_info=True)

    # -- buttons

    @discord.ui.button(label="Save", style=discord.ButtonStyle.green, row=2)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        # Saving reads the allowed lights from the bridge; defer so a slow bridge doesn't run
        # out Discord's 3 s. Errors go out as an ephemeral follow-up; the builder stays open.
        await interaction.response.defer()
        ordered = sorted(self.actions.values(), key=lambda a: self.names[a.light_id].casefold())
        data = SceneInput(name=self.name, actions=tuple(ordered))
        if self.scene_id is None:
            saved = await self.scenes.create(interaction.user.id, data)
        else:
            saved = await self.scenes.update(self.scene_id, data)
        self.stop()
        count = len(saved.actions)
        plural = "light" if count == 1 else "lights"
        await interaction.edit_original_response(
            content=f"Saved scene **{escape(saved.name)}** ({count} {plural}).",
            embed=None,
            view=None,
            allowed_mentions=NO_MENTIONS,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey, row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Nothing saved.", embed=None, view=None)


class _SetLightsSelect(discord.ui.Select["SceneBuilder"]):
    def __init__(self, builder: SceneBuilder) -> None:
        ordered = sorted(builder.names.items(), key=lambda item: item[1].casefold())
        options = [
            discord.SelectOption(label=name[:100], value=light_id)
            for light_id, name in ordered[:SELECT_LIMIT]
        ]
        super().__init__(
            placeholder="Set lights…",
            min_values=1,
            max_values=max(len(options), 1),
            options=options or [discord.SelectOption(label="No lights", value="-")],
            disabled=not options,
            row=0,
        )
        self.builder = builder

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ActionForm(self.builder, list(self.values)))


class _RemoveLightsSelect(discord.ui.Select["SceneBuilder"]):
    def __init__(self, builder: SceneBuilder) -> None:
        in_scene = sorted(builder.actions, key=lambda light_id: builder.names[light_id].casefold())
        options = [
            discord.SelectOption(label=builder.names[light_id][:100], value=light_id)
            for light_id in in_scene[:SELECT_LIMIT]
        ]
        super().__init__(
            placeholder="Remove lights…",
            min_values=1,
            max_values=max(len(options), 1),
            options=options or [discord.SelectOption(label="No lights", value="-")],
            disabled=not options,
            row=1,
        )
        self.builder = builder

    async def callback(self, interaction: discord.Interaction) -> None:
        for light_id in self.values:
            self.builder.actions.pop(light_id, None)
        await self.builder.refresh(interaction)


class ActionForm(discord.ui.Modal):
    """State (on/off), Colour and Brightness for the picked lights; prefilled when they all share
    one action. A bad value shows an ephemeral error and leaves the builder as it was."""

    def __init__(self, builder: SceneBuilder, light_ids: list[str]) -> None:
        if len(light_ids) == 1:
            title = f"Set {builder.names[light_ids[0]]}"
        else:
            title = f"Set {len(light_ids)} lights"
        super().__init__(title=title[:MODAL_TITLE_MAX], timeout=BUILDER_TIMEOUT)
        self.builder = builder
        self.light_ids = light_ids
        shared = builder.shared_action(light_ids)
        is_on = shared is None or shared.on

        self.state: discord.ui.Select = discord.ui.Select(
            options=[
                discord.SelectOption(label="On", value="on", default=is_on),
                discord.SelectOption(label="Off", value="off", default=not is_on),
            ],
        )
        self.color: discord.ui.TextInput = discord.ui.TextInput(
            placeholder="#ff8800 or 2700K",
            default=shared.color if shared is not None else None,
            required=False,
            max_length=20,
        )
        self.brightness: discord.ui.TextInput = discord.ui.TextInput(
            placeholder="0-100",
            default=(
                str(shared.brightness)
                if shared is not None and shared.brightness is not None
                else None
            ),
            required=False,
            max_length=3,
        )
        self.add_item(discord.ui.Label(text="State", component=self.state))
        self.add_item(
            discord.ui.Label(
                text="Colour",
                description="Hex or white temperature; empty keeps the light's colour",
                component=self.color,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Brightness (%)",
                description="0 is the lowest glow, not off; empty keeps the light's brightness",
                component=self.brightness,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        state = self.state.values[0] if self.state.values else "on"
        for light_id in self.light_ids:
            if light_id in self.builder.names:  # picked from the builder's own options
                self.builder.actions[light_id] = parse_action(
                    light_id, state, self.color.value, self.brightness.value
                )
        await self.builder.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _show_error(interaction, error)


async def _show_error(interaction: discord.Interaction, error: Exception) -> None:
    text = error_text(error)
    if text is None:
        log.error("Scene builder failed", exc_info=error)
        text = UNEXPECTED_MESSAGE
    try:
        await send_ephemeral(interaction, text)
    except discord.HTTPException:
        log.warning("Couldn't send a scene builder error", exc_info=True)
