"""SettingsService against PostgreSQL: the reset scene (D18, D19) and the daytime confirmation
(D25)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aurorahue.core.errors import NotFound
from aurorahue.services.scenes import ActionInput, SceneInput, SceneService
from aurorahue.services.settings import SettingsService, SettingsView
from tests.support.services import DESK_ID


async def make_scene(scenes: SceneService, name: str) -> int:
    action = ActionInput(light_id=DESK_ID, on=True)
    return (await scenes.create(1, SceneInput(name=name, actions=(action,)))).id


async def test_nothing_set_after_migration(settings: SettingsService) -> None:
    assert await settings.get_settings() == SettingsView()


async def test_set_and_clear_the_reset_scene(
    settings: SettingsService, scenes: SceneService
) -> None:
    scene_id = await make_scene(scenes, "Evening")

    assert await settings.set_reset_scene(scene_id) == SettingsView(
        reset_scene_id=scene_id, reset_scene_name="Evening"
    )
    assert await settings.get_settings() == SettingsView(
        reset_scene_id=scene_id, reset_scene_name="Evening"
    )

    assert await settings.set_reset_scene(None) == SettingsView()
    assert await settings.get_settings() == SettingsView()


async def test_replace_the_reset_scene(settings: SettingsService, scenes: SceneService) -> None:
    first = await make_scene(scenes, "Evening")
    second = await make_scene(scenes, "Night")
    await settings.set_reset_scene(first)

    view = await settings.set_reset_scene(second)

    assert view.reset_scene_name == "Night"


async def test_unknown_scene_refused(settings: SettingsService) -> None:
    with pytest.raises(NotFound):
        await settings.set_reset_scene(999_999)
    assert await settings.get_settings() == SettingsView()


async def test_set_works_without_the_row(
    session: AsyncSession, settings: SettingsService, scenes: SceneService
) -> None:
    scene_id = await make_scene(scenes, "Evening")
    await session.execute(text("DELETE FROM bot_settings"))

    assert await settings.get_settings() == SettingsView()
    assert (await settings.set_reset_scene(scene_id)).reset_scene_id == scene_id


async def test_db_allows_only_row_1(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(text("INSERT INTO bot_settings (id) VALUES (2)"))


async def test_daytime_confirm_off_after_migration(settings: SettingsService) -> None:
    assert (await settings.get_settings()).daytime_confirm is False


async def test_switch_daytime_confirm_on_and_off(settings: SettingsService) -> None:
    assert await settings.set_daytime_confirm(True) == SettingsView(daytime_confirm=True)
    assert await settings.get_settings() == SettingsView(daytime_confirm=True)

    assert await settings.set_daytime_confirm(False) == SettingsView()
    assert await settings.get_settings() == SettingsView()


async def test_daytime_confirm_keeps_the_reset_scene(
    settings: SettingsService, scenes: SceneService
) -> None:
    scene_id = await make_scene(scenes, "Evening")
    await settings.set_reset_scene(scene_id)

    view = await settings.set_daytime_confirm(True)

    assert view == SettingsView(
        reset_scene_id=scene_id, reset_scene_name="Evening", daytime_confirm=True
    )


async def test_reset_scene_keeps_daytime_confirm(
    settings: SettingsService, scenes: SceneService
) -> None:
    scene_id = await make_scene(scenes, "Evening")
    await settings.set_daytime_confirm(True)

    view = await settings.set_reset_scene(scene_id)

    assert view.daytime_confirm is True


async def test_daytime_confirm_works_without_the_row(
    session: AsyncSession, settings: SettingsService
) -> None:
    await session.execute(text("DELETE FROM bot_settings"))

    assert await settings.set_daytime_confirm(True) == SettingsView(daytime_confirm=True)
