"""Rendering of scenes for Discord: the scene builder's action lines (D13, D16), the `/scene list`
lines (§7) and the form parsing (D9, D10, D13). All pure: no bot, no database, no bridge."""

import pytest

from aurorahue.cogs.scene_builder import action_line, builder_lines, parse_action
from aurorahue.cogs.scenes import NOT_CONTROLLABLE, RESET_MARK, scene_detail_lines, scene_list_lines
from aurorahue.core.errors import InvalidInput
from aurorahue.services.scenes import ActionInput, SceneView


def on(light_id: str = "a", color: str | None = None, brightness: int | None = None) -> ActionInput:
    return ActionInput(light_id=light_id, on=True, color=color, brightness=brightness)


def off(light_id: str = "a") -> ActionInput:
    return ActionInput(light_id=light_id, on=False)


def scene(
    name: str, actions: tuple[ActionInput, ...], *, is_reset: bool = False, scene_id: int = 1
) -> SceneView:
    return SceneView(id=scene_id, name=name, actions=actions, is_reset=is_reset)


@pytest.mark.parametrize(
    ("name", "action", "expected"),
    [
        pytest.param(
            "Desk",
            ActionInput(light_id="a", on=True, color="#ff8800", brightness=40),
            "**Desk** — on, #ff8800, 40%",
            id="on-all-fields",
        ),
        pytest.param(
            "Desk",
            ActionInput(light_id="a", on=True, color="2700K", brightness=40),
            "**Desk** — on, 2700K, 40%",
            id="on-kelvin",
        ),
        pytest.param("Desk", on(brightness=0), "**Desk** — on, 0%", id="on-brightness-zero"),
        pytest.param("Desk", on(), "**Desk** — on", id="on-nothing"),
        pytest.param("Hallway", off(), "**Hallway** — off", id="off"),
        pytest.param(
            "Desk_1 *big*",
            off(),
            "**Desk\\_1 \\*big\\*** — off",
            id="name-escaped",
        ),
    ],
)
def test_action_line(name: str, action: ActionInput, expected: str) -> None:
    assert action_line(name, action) == expected


def test_action_line_breaks_mentions() -> None:
    line = action_line("@everyone", off())
    assert "@everyone" not in line


@pytest.mark.parametrize(
    ("actions", "names", "expected"),
    [
        pytest.param(
            {"1": on("1"), "2": on("2"), "3": on("3")},
            {"1": "lamp", "2": "Desk", "3": "attic"},
            [
                "**attic** — on",
                "**Desk** — on",
                "**lamp** — on",
            ],
            id="sorted-ignoring-case",
        ),
        pytest.param({}, {}, [], id="empty"),
    ],
)
def test_builder_lines(
    actions: dict[str, ActionInput], names: dict[str, str], expected: list[str]
) -> None:
    assert builder_lines(actions, names) == expected


@pytest.mark.parametrize(
    ("scenes", "expected"),
    [
        pytest.param(
            [scene("Evening", (on("a"), on("b"), off("c")))],
            ["**Evening** (3 lights)"],
            id="plural",
        ),
        pytest.param(
            [scene("Evening", (on("a"),))],
            ["**Evening** (1 light)"],
            id="singular",
        ),
        pytest.param(
            [scene("Night", (on("a"), off("b")), is_reset=True)],
            [f"**Night** (2 lights) {RESET_MARK}"],
            id="reset-marked",
        ),
        pytest.param(
            [scene("my_scene", (on("a"),))],
            ["**my\\_scene** (1 light)"],
            id="name-escaped",
        ),
        pytest.param([], [], id="empty"),
    ],
)
def test_scene_list_lines(scenes: list[SceneView], expected: list[str]) -> None:
    assert scene_list_lines(scenes) == expected


@pytest.mark.parametrize(
    ("scene_view", "names", "expected"),
    [
        pytest.param(
            scene(
                "Evening",
                (
                    ActionInput(light_id="b", on=True, color="#ff8800", brightness=40),
                    off("a"),
                ),
            ),
            {"a": "Attic", "b": "desk"},
            ["**Attic** — off", "**desk** — on, #ff8800, 40%"],
            id="sorted-all-allowed",
        ),
        pytest.param(
            scene(
                "Evening",
                (
                    ActionInput(light_id="hidden-uuid", on=True, color="2700K"),
                    on("a"),
                ),
            ),
            {"a": "Desk"},
            ["**Desk** — on", f"{NOT_CONTROLLABLE} — on, 2700K"],
            id="disallowed-last-and-unnamed",
        ),
    ],
)
def test_scene_detail_lines(
    scene_view: SceneView, names: dict[str, str], expected: list[str]
) -> None:
    assert scene_detail_lines(scene_view, names) == expected


def test_scene_detail_lines_hide_disallowed_id() -> None:
    view = scene("Evening", (ActionInput(light_id="hidden-uuid", on=False), on("a")))
    lines = scene_detail_lines(view, {"a": "Desk"})
    assert all("hidden-uuid" not in line for line in lines)


@pytest.mark.parametrize(
    ("light_id", "state", "color", "brightness", "expected"),
    [
        pytest.param(
            "x",
            "on",
            " #FF8800 ",
            "40",
            ActionInput(light_id="x", on=True, color="#ff8800", brightness=40),
            id="hex-and-brightness",
        ),
        pytest.param(
            "x",
            "on",
            "2700 k",
            "",
            ActionInput(light_id="x", on=True, color="2700K", brightness=None),
            id="kelvin-spaced",
        ),
        pytest.param(
            "x",
            "on",
            "",
            "",
            ActionInput(light_id="x", on=True, color=None, brightness=None),
            id="all-empty",
        ),
        pytest.param(
            "x",
            "off",
            "",
            "",
            ActionInput(light_id="x", on=False, color=None, brightness=None),
            id="off",
        ),
    ],
)
def test_parse_action(
    light_id: str,
    state: str,
    color: str,
    brightness: str,
    expected: ActionInput,
) -> None:
    assert parse_action(light_id, state, color, brightness) == expected


@pytest.mark.parametrize(
    ("state", "color", "brightness"),
    [
        pytest.param("off", "#ff8800", "", id="off-with-colour"),
        pytest.param("off", "", "40", id="off-with-brightness"),
        pytest.param("on", "#zzz", "", id="bad-hex"),
        pytest.param("on", "2700", "", id="colour-without-unit"),
        pytest.param("on", "", "101", id="brightness-over-100"),
        pytest.param("on", "", "abc", id="brightness-not-number"),
        pytest.param("on", "", "-5", id="brightness-negative"),
    ],
)
def test_parse_action_rejects(state: str, color: str, brightness: str) -> None:
    with pytest.raises(InvalidInput):
        parse_action("x", state, color, brightness)
