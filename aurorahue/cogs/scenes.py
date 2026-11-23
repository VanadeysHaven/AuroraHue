"""Scene commands (D15–D17, D19, D21): the `/scene` group and `/reset`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import discord
from discord import app_commands
from discord.ext import commands

from aurorahue.cogs.common import (
    NO_MENTIONS,
    ConfirmView,
    confirm_if_daytime,
    escape,
    is_allowed,
    light_service,
    report_text,
    scene_autocomplete,
    scene_service,
    settings_service,
)
from aurorahue.cogs.scene_builder import SceneBuilder, action_line, action_summary
from aurorahue.core.errors import InvalidInput, NameTaken, NotFound
from aurorahue.db.models import SCENE_NAME_MAX
from aurorahue.hue.hue_client import BridgeLight
from aurorahue.services.scenes import SceneView

RESET_MARK = "⟲"
NOT_CONTROLLABLE = "(not controllable)"


# --- Rendering (pure; tests/unit/test_scene_render.py) -------------------------------------


def scene_list_lines(scenes: Sequence[SceneView]) -> list[str]:
    """`/scene list`: "**Evening** (3 lights)", the reset scene marked ⟲ (§7)."""
    lines = []
    for scene in scenes:
        count = len(scene.actions)
        plural = "light" if count == 1 else "lights"
        mark = f" {RESET_MARK}" if scene.is_reset else ""
        lines.append(f"**{escape(scene.name)}** ({count} {plural}){mark}")
    return lines


def scene_detail_lines(scene: SceneView, names: Mapping[str, str]) -> list[str]:
    """`/scene list scene:…`: one line per action, allowed lights by name (sorted), the rest as
    "(not controllable)" at the end (D4: a disallowed light's name is never shown).
    `names` maps the allowed light IDs to their names."""
    known = sorted(
        (a for a in scene.actions if a.light_id in names),
        key=lambda a: names[a.light_id].casefold(),
    )
    lines = [action_line(names[a.light_id], a) for a in known]
    lines += [
        f"{NOT_CONTROLLABLE} — {action_summary(a)}"
        for a in scene.actions
        if a.light_id not in names
    ]
    return lines


# --- Commands -------------------------------------------------------------------------------


class Scenes(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    scene = app_commands.Group(name="scene", description="Named sets of light settings.")

    @scene.command(name="add", description="Create a scene in the scene editor.")
    @app_commands.describe(name="The new scene's name")
    @is_allowed()
    async def add(
        self,
        interaction: discord.Interaction,
        name: app_commands.Range[str, 1, SCENE_NAME_MAX],
    ) -> None:
        name = name.strip()
        if not name:
            raise InvalidInput(f"A scene name is 1 to {SCENE_NAME_MAX} characters.")
        await _check_name_free(interaction, name, exclude_id=None)
        builder = SceneBuilder(
            owner_id=interaction.user.id,
            scenes=scene_service(interaction),
            lights=await _controllable_lights(interaction),
            name=name,
        )
        await _open_builder(interaction, builder)

    @scene.command(name="edit", description="Change a scene in the scene editor.")
    @app_commands.describe(scene="The scene to change", new_name="Rename it (applied on Save)")
    @app_commands.rename(new_name="new-name")
    @app_commands.autocomplete(scene=scene_autocomplete)
    @is_allowed()
    async def edit(
        self,
        interaction: discord.Interaction,
        scene: str,
        new_name: app_commands.Range[str, 1, SCENE_NAME_MAX] | None = None,
    ) -> None:
        current = await scene_service(interaction).get(scene)
        name = current.name
        if new_name is not None and new_name.strip():
            name = new_name.strip()
            await _check_name_free(interaction, name, exclude_id=current.id)
        builder = SceneBuilder(
            owner_id=interaction.user.id,
            scenes=scene_service(interaction),
            lights=await _controllable_lights(interaction),
            name=name,
            scene_id=current.id,
            old_name=current.name,
            actions=current.actions,
        )
        await _open_builder(interaction, builder)

    @scene.command(name="list", description="Show the scenes, or one scene's lights.")
    @app_commands.describe(scene="A scene to show the lights of")
    @app_commands.autocomplete(scene=scene_autocomplete)
    @is_allowed()
    async def list_scenes(self, interaction: discord.Interaction, scene: str | None = None) -> None:
        if scene is None:
            scenes = await scene_service(interaction).list_scenes()
            text = "\n".join(scene_list_lines(scenes)) or (
                "No scenes yet. Create one with /scene add."
            )
            await interaction.response.send_message(
                text, ephemeral=True, allowed_mentions=NO_MENTIONS
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        found = await scene_service(interaction).get(scene)
        names = {light.id: light.name for light in await light_service(interaction).allowed()}
        header = f"**{escape(found.name)}**" + (f" {RESET_MARK}" if found.is_reset else "")
        text = "\n".join([header, *scene_detail_lines(found, names)])
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=NO_MENTIONS)

    @scene.command(name="delete", description="Delete a scene.")
    @app_commands.describe(scene="The scene to delete")
    @app_commands.autocomplete(scene=scene_autocomplete)
    @is_allowed()
    async def delete(self, interaction: discord.Interaction, scene: str) -> None:
        found = await scene_service(interaction).get(scene)
        count = len(found.actions)
        plural = "light" if count == 1 else "lights"
        question = f"Delete scene **{escape(found.name)}** ({count} {plural})?"
        if found.is_reset:  # D19
            question += (
                "\nThis is the reset scene; `/reset` will do nothing until you pick another."
            )
        # D19: ask first, ephemerally, and only the caller can answer.
        view = ConfirmView(interaction.user.id, confirm_label="Delete", confirm_text="Deleting…")
        await interaction.response.send_message(
            question, view=view, ephemeral=True, allowed_mentions=NO_MENTIONS
        )
        await view.wait()
        if view.value is None:
            await interaction.edit_original_response(
                content="No answer; nothing deleted.", view=None
            )
            return
        if not view.value:
            return  # the view already edited the message
        deleted = await scene_service(interaction).delete(found.id)
        text = f"Deleted scene **{escape(deleted.name)}**."
        if deleted.is_reset:
            text += " No reset scene is set now."
        await interaction.edit_original_response(content=text, view=None)

    @scene.command(name="run", description="Run a scene.")
    @app_commands.describe(scene="The scene to run")
    @app_commands.autocomplete(scene=scene_autocomplete)
    @is_allowed()
    async def run(self, interaction: discord.Interaction, scene: str) -> None:
        found = await scene_service(interaction).get(scene)
        await run_scene(interaction, found)

    @app_commands.command(name="reset", description="Run the reset scene.")
    @is_allowed()
    async def reset(self, interaction: discord.Interaction) -> None:
        current = await settings_service(interaction).get_settings()
        if current.reset_scene_id is None:
            await interaction.response.send_message(
                "No reset scene set. Pick one with `/settings reset-scene`.",
                ephemeral=True,
                allowed_mentions=NO_MENTIONS,
            )
            return
        scene = await scene_service(interaction).get_by_id(current.reset_scene_id)
        await run_scene(interaction, scene)


async def run_scene(interaction: discord.Interaction, scene: SceneView) -> None:
    """D17, D21, D22: run a scene publicly. Switching on a light asks first in daytime."""
    switching_on = [a.light_id for a in scene.actions if a.on]
    if not await confirm_if_daytime(interaction, switching_on):
        return
    report = await scene_service(interaction).run(scene.id)
    text = f"Ran scene **{escape(scene.name)}**. {report_text(report, 'Set')}"
    await interaction.followup.send(text, allowed_mentions=NO_MENTIONS)


async def _check_name_free(
    interaction: discord.Interaction, name: str, *, exclude_id: int | None
) -> None:
    """Early `NameTaken` (the service checks again on Save; last save wins, D16)."""
    try:
        existing = await scene_service(interaction).get(name)
    except NotFound:
        return
    if existing.id != exclude_id:
        raise NameTaken(f'There is already a scene named "{existing.name}".')


async def _controllable_lights(interaction: discord.Interaction) -> list[BridgeLight]:
    lights = await light_service(interaction).allowed()
    if not lights:
        raise NotFound("There are no lights the bot may control.")
    return lights


async def _open_builder(interaction: discord.Interaction, builder: SceneBuilder) -> None:
    await interaction.response.send_message(
        embed=builder.embed(), view=builder, ephemeral=True, allowed_mentions=NO_MENTIONS
    )
    builder.origin = interaction


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Scenes(bot))
