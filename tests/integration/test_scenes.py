"""SceneService against PostgreSQL, with a fake bridge (D13–D17, D19)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aurorahue.core.color import InvalidColor
from aurorahue.core.errors import InvalidInput, NameTaken, NotAllowed, NotFound
from aurorahue.db.models import Scene, SceneAction
from aurorahue.hue.hue_client import LightState
from aurorahue.services.lights import Outcome
from aurorahue.services.scenes import ActionInput, SceneInput, SceneService
from aurorahue.services.settings import SettingsService
from tests.support.clock import FixedClock
from tests.support.hue import FakeClient
from tests.support.services import (
    DESK_ID,
    GARAGE_ID,
    GONE_ID,
    HALLWAY_ID,
    PORCH_ID,
    light_service,
    session_factory,
)

ACTOR = 111


def on(light_id: str, color: str | None = None, brightness: int | None = None) -> ActionInput:
    return ActionInput(light_id=light_id, on=True, color=color, brightness=brightness)


def off(light_id: str) -> ActionInput:
    return ActionInput(light_id=light_id, on=False)


def scene(name: str, *actions: ActionInput) -> SceneInput:
    return SceneInput(name=name, actions=actions)


async def count_actions(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(SceneAction)) or 0


# create / list / get


async def test_create_list_and_get_any_case(
    scenes: SceneService, session: AsyncSession, clock: FixedClock
) -> None:
    start = clock.now()
    created = await scenes.create(
        ACTOR, scene("  Evening ", on(DESK_ID, "#ff8800", 40), off(HALLWAY_ID))
    )
    await scenes.create(ACTOR, scene("alpha", on(PORCH_ID)))

    assert created.name == "Evening"
    assert created.actions == (on(DESK_ID, "#ff8800", 40), off(HALLWAY_ID))
    assert not created.is_reset
    assert [s.name for s in await scenes.list_scenes()] == ["alpha", "Evening"]
    assert await scenes.get("EVENING") == created
    assert await scenes.get(" evening ") == created

    row = await session.get(Scene, created.id)
    assert row is not None
    assert (row.created_by, row.created_at, row.updated_at) == (ACTOR, start, start)


@pytest.mark.parametrize(("first", "second"), [("Evening", "evening"), ("Evening", " EVENING ")])
async def test_name_taken_ignores_case(scenes: SceneService, first: str, second: str) -> None:
    await scenes.create(ACTOR, scene(first, on(DESK_ID)))

    with pytest.raises(NameTaken):
        await scenes.create(ACTOR, scene(second, on(HALLWAY_ID)))


@pytest.mark.parametrize("name", ["", "   ", "x" * 51])
async def test_name_length_refused(scenes: SceneService, name: str) -> None:
    with pytest.raises(InvalidInput):
        await scenes.create(ACTOR, scene(name, on(DESK_ID)))


async def test_name_of_50_chars_accepted(scenes: SceneService) -> None:
    created = await scenes.create(ACTOR, scene("x" * 50, on(DESK_ID)))

    assert created.name == "x" * 50


async def test_no_actions_refused(scenes: SceneService) -> None:
    with pytest.raises(InvalidInput):
        await scenes.create(ACTOR, scene("Empty"))


async def test_two_actions_for_one_light_refused(scenes: SceneService) -> None:
    with pytest.raises(InvalidInput):
        await scenes.create(ACTOR, scene("Twice", on(DESK_ID), off(DESK_ID)))


@pytest.mark.parametrize(
    "action",
    [
        ActionInput(light_id=DESK_ID, on=False, color="#ff8800"),
        ActionInput(light_id=DESK_ID, on=False, brightness=10),
    ],
)
async def test_off_with_colour_or_brightness_refused(
    scenes: SceneService, action: ActionInput
) -> None:
    with pytest.raises(InvalidInput):
        await scenes.create(ACTOR, scene("Off", action))


@pytest.mark.parametrize(
    ("given", "stored"),
    [("2700K", "2700K"), ("#ff8800", "#ff8800"), ("#FF8800", "#ff8800"), ("2700 k", "2700K")],
)
async def test_colour_stored_normalised(scenes: SceneService, given: str, stored: str) -> None:
    created = await scenes.create(ACTOR, scene("Colour", on(DESK_ID, given)))

    assert created.actions[0].color == stored


@pytest.mark.parametrize("color", ["1500K", "2700", "#000000", "nope"])
async def test_bad_colour_refused(scenes: SceneService, color: str) -> None:
    with pytest.raises(InvalidColor):
        await scenes.create(ACTOR, scene("Bad", on(DESK_ID, color)))


@pytest.mark.parametrize("brightness", [-1, 101])
async def test_bad_brightness_refused(scenes: SceneService, brightness: int) -> None:
    with pytest.raises(InvalidInput):
        await scenes.create(ACTOR, scene("Bad", on(DESK_ID, brightness=brightness)))


@pytest.mark.parametrize("light_id", [GARAGE_ID, GONE_ID])
async def test_disallowed_or_missing_light_refused_at_save(
    scenes: SceneService, session: AsyncSession, light_id: str
) -> None:
    with pytest.raises(NotAllowed):
        await scenes.create(ACTOR, scene("Nope", on(DESK_ID), on(light_id)))

    assert await count_actions(session) == 0


# update


async def test_update_replaces_actions_and_renames(
    scenes: SceneService, session: AsyncSession, clock: FixedClock
) -> None:
    start = clock.now()
    created = await scenes.create(ACTOR, scene("Evening", on(DESK_ID, "#ff8800"), off(PORCH_ID)))
    clock.advance(timedelta(hours=1))

    updated = await scenes.update(
        created.id, scene("Night", on(DESK_ID, "2200K", 5), on(HALLWAY_ID))
    )

    assert updated.id == created.id
    assert updated.name == "Night"
    assert updated.actions == (on(DESK_ID, "2200K", 5), on(HALLWAY_ID))
    assert await count_actions(session) == 2
    row = await session.get(Scene, created.id)
    assert row is not None
    assert (row.created_at, row.updated_at) == (start, start + timedelta(hours=1))
    with pytest.raises(NotFound):
        await scenes.get("Evening")


async def test_update_may_keep_its_own_name_in_another_case(scenes: SceneService) -> None:
    created = await scenes.create(ACTOR, scene("Evening", on(DESK_ID)))

    updated = await scenes.update(created.id, scene("EVENING", on(DESK_ID)))

    assert updated.name == "EVENING"


async def test_update_to_another_scenes_name_refused(scenes: SceneService) -> None:
    await scenes.create(ACTOR, scene("Evening", on(DESK_ID)))
    night = await scenes.create(ACTOR, scene("Night", on(DESK_ID)))

    with pytest.raises(NameTaken):
        await scenes.update(night.id, scene("evening", on(DESK_ID)))


async def test_update_validates_like_create(scenes: SceneService) -> None:
    created = await scenes.create(ACTOR, scene("Evening", on(DESK_ID)))

    with pytest.raises(NotAllowed):
        await scenes.update(created.id, scene("Evening", on(GARAGE_ID)))
    assert (await scenes.get("Evening")).actions == (on(DESK_ID),)


# delete and the reset scene


async def test_delete_cascades_actions(scenes: SceneService, session: AsyncSession) -> None:
    created = await scenes.create(ACTOR, scene("Evening", on(DESK_ID), off(HALLWAY_ID)))

    deleted = await scenes.delete(created.id)

    assert deleted.name == "Evening"
    assert await count_actions(session) == 0
    assert await scenes.list_scenes() == []


async def test_deleting_the_reset_scene_clears_the_setting(
    scenes: SceneService, settings: SettingsService
) -> None:
    created = await scenes.create(ACTOR, scene("Evening", on(DESK_ID)))
    await settings.set_reset_scene(created.id)
    assert (await scenes.get("Evening")).is_reset

    deleted = await scenes.delete(created.id)

    assert deleted.is_reset
    assert (await settings.get_settings()).reset_scene_id is None


async def test_list_marks_the_reset_scene(scenes: SceneService, settings: SettingsService) -> None:
    await scenes.create(ACTOR, scene("Evening", on(DESK_ID)))
    night = await scenes.create(ACTOR, scene("Night", on(DESK_ID)))
    await settings.set_reset_scene(night.id)

    assert [(s.name, s.is_reset) for s in await scenes.list_scenes()] == [
        ("Evening", False),
        ("Night", True),
    ]


# unknown scenes


async def test_unknown_scene_not_found(scenes: SceneService) -> None:
    with pytest.raises(NotFound):
        await scenes.get("nope")
    with pytest.raises(NotFound):
        await scenes.get_by_id(999_999)
    with pytest.raises(NotFound):
        await scenes.update(999_999, scene("x", on(DESK_ID)))
    with pytest.raises(NotFound):
        await scenes.delete(999_999)
    with pytest.raises(NotFound):
        await scenes.run(999_999)


# run


async def test_run_builds_light_states(scenes: SceneService, fake_bridge: FakeClient) -> None:
    created = await scenes.create(
        ACTOR,
        scene(
            "Evening",
            on(DESK_ID, "#ff0000", 40),
            on(HALLWAY_ID, "2700K"),
            off(PORCH_ID),
        ),
    )

    report = await scenes.run(created.id)

    assert dict(fake_bridge.applied) == {
        DESK_ID: LightState(on=True, xy=(0.6401, 0.33), brightness=40.0),
        HALLWAY_ID: LightState(on=True, mirek=370),
        PORCH_ID: LightState(on=False),
    }
    assert report.changed == 3


async def test_run_clamps_kelvin_to_the_lights_range(
    scenes: SceneService, fake_bridge: FakeClient
) -> None:
    created = await scenes.create(ACTOR, scene("Warm", on(HALLWAY_ID, "2000K")))

    await scenes.run(created.id)

    assert fake_bridge.applied == [(HALLWAY_ID, LightState(on=True, mirek=454))]


async def test_run_skips_lights_no_longer_allowed_or_gone(
    session: AsyncSession, scenes: SceneService, fake_bridge: FakeClient, clock: FixedClock
) -> None:
    created = await scenes.create(
        ACTOR, scene("Evening", on(DESK_ID), on(HALLWAY_ID), on(PORCH_ID))
    )
    # The access file now also blocks Hallway (restart), and Porch left the bridge.
    fake_bridge.lights = [light for light in fake_bridge.lights if light.id != PORCH_ID]
    later = SceneService(
        session_factory(session),
        light_service(fake_bridge, clock, blacklist=(GARAGE_ID, HALLWAY_ID)),
        clock,
    )

    report = await later.run(created.id)

    assert [light_id for light_id, _ in fake_bridge.applied] == [DESK_ID]
    assert {r.light_id: r.outcome for r in report.results} == {
        DESK_ID: Outcome.OK,
        HALLWAY_ID: Outcome.NOT_ALLOWED,
        PORCH_ID: Outcome.MISSING,
    }


async def test_run_reports_colour_skipped(scenes: SceneService, fake_bridge: FakeClient) -> None:
    created = await scenes.create(ACTOR, scene("Red", on(HALLWAY_ID, "#ff0000", 20)))

    report = await scenes.run(created.id)

    assert fake_bridge.applied == [(HALLWAY_ID, LightState(on=True, brightness=20.0))]
    assert report.names(Outcome.COLOR_SKIPPED) == ["Hallway"]


# database checks (written directly, bypassing the service)


async def _insert_scene(session: AsyncSession) -> int:
    return (
        await session.execute(
            text(
                "INSERT INTO scenes (name, created_by, created_at, updated_at) "
                "VALUES ('Raw', 1, now(), now()) RETURNING id"
            )
        )
    ).scalar_one()


@pytest.mark.parametrize(
    ("is_on", "color", "brightness"),
    [
        (True, "#FF8800", None),
        (True, "2700k", None),
        (True, "ff8800", None),
        (True, None, 101),
        (True, None, -1),
        (False, "#ff8800", None),
        (False, None, 10),
    ],
)
async def test_db_rejects_bad_actions(
    session: AsyncSession, is_on: bool, color: str | None, brightness: int | None
) -> None:
    scene_id = await _insert_scene(session)

    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                text(
                    "INSERT INTO scene_actions (scene_id, light_id, is_on, color, brightness) "
                    "VALUES (:scene_id, :light_id, :is_on, :color, :brightness)"
                ),
                {
                    "scene_id": scene_id,
                    "light_id": DESK_ID,
                    "is_on": is_on,
                    "color": color,
                    "brightness": brightness,
                },
            )


async def test_db_accepts_good_actions(session: AsyncSession) -> None:
    scene_id = await _insert_scene(session)

    for light_id, color in ((DESK_ID, "#ff8800"), (HALLWAY_ID, "2700K")):
        await session.execute(
            text(
                "INSERT INTO scene_actions (scene_id, light_id, is_on, color, brightness) "
                "VALUES (:scene_id, :light_id, true, :color, 100)"
            ),
            {"scene_id": scene_id, "light_id": light_id, "color": color},
        )

    assert await count_actions(session) == 2


@pytest.mark.parametrize("name", ["", "x" * 51])
async def test_db_rejects_bad_scene_names(session: AsyncSession, name: str) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                text(
                    "INSERT INTO scenes (name, created_by, created_at, updated_at) "
                    "VALUES (:name, 1, now(), now())"
                ),
                {"name": name},
            )
