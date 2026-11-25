"""Reply text for light changes (`report_text`), app-command errors (`error_text`) and
`/settings` (`settings_text`)."""

import pytest
from discord import app_commands

from aurorahue.cogs.common import error_text, report_text
from aurorahue.cogs.lights import is_bare
from aurorahue.cogs.settings import excluded_text, settings_text
from aurorahue.core.errors import BridgeUnavailable, NotFound
from aurorahue.services.lights import ApplyReport, LightResult, Outcome
from aurorahue.services.settings import SettingsView

OK = Outcome.OK
COLOR_SKIPPED = Outcome.COLOR_SKIPPED
FAILED = Outcome.FAILED
NOT_ALLOWED = Outcome.NOT_ALLOWED
MISSING = Outcome.MISSING
QUEUED = Outcome.QUEUED
LIGHT_NAMES = {"id-desk": "Desk", "id-hall": "Hallway", "id-star": "*Star*"}


def report(*results: tuple[str, Outcome]) -> ApplyReport:
    return ApplyReport(
        tuple(
            LightResult(light_id=f"id-{i}", name=name, outcome=outcome)
            for i, (name, outcome) in enumerate(results)
        )
    )


def wrapped(original: Exception) -> app_commands.CommandInvokeError:
    err = app_commands.CommandInvokeError.__new__(app_commands.CommandInvokeError)
    err.original = original
    return err


@pytest.mark.parametrize(
    ("results", "verb", "suffix", "expected"),
    [
        pytest.param([("Desk", OK)], "Turned on", "", "Turned on Desk.", id="one-ok"),
        pytest.param(
            [("A", OK), ("B", OK), ("C", OK)], "Turned on", "", "Turned on 3 lights.", id="three-ok"
        ),
        pytest.param(
            [("A", OK), ("B", OK)],
            "Set",
            " to #ff8800",
            "Set 2 lights to #ff8800.",
            id="suffix",
        ),
        pytest.param(
            [("Desk", OK), ("Hallway", COLOR_SKIPPED)],
            "Set",
            " to #ff8800",
            "Set 2 lights to #ff8800. Colour skipped for: Hallway.",
            id="colour-skipped",
        ),
        pytest.param(
            [("Desk", OK), ("Hall", QUEUED), ("Lamp", QUEUED)],
            "Set",
            " to 30% brightness",
            "Set Desk to 30% brightness. Queued until switched on (30 min): Hall, Lamp.",
            id="some-queued",
        ),
        pytest.param(
            [("Hall", QUEUED)],
            "Set",
            " to #ff8800",
            "Queued until switched on (30 min): Hall.",
            id="all-queued",
        ),
        pytest.param(
            [("Desk", OK), ("Hall", OK), ("Lamp", FAILED)],
            "Turned on",
            "",
            "Turned on 2 lights. Didn't answer: Lamp.",
            id="with-failures",
        ),
        pytest.param(
            [("Desk", FAILED), ("Lamp", FAILED)],
            "Turned on",
            "",
            "No lights changed. Didn't answer: Desk, Lamp.",
            id="all-failed",
        ),
        pytest.param([], "Turned on", "", "No lights changed.", id="empty"),
        pytest.param(
            [("Desk", OK), ("Old", NOT_ALLOWED), ("x", MISSING), ("y", MISSING)],
            "Turned on",
            "",
            "Turned on Desk. Not controllable any more: Old. "
            "2 lights aren't on the bridge any more.",
            id="not-allowed-and-missing",
        ),
        pytest.param(
            [("Desk", OK), ("x", MISSING)],
            "Turned on",
            "",
            "Turned on Desk. 1 light isn't on the bridge any more.",
            id="one-missing",
        ),
    ],
)
def test_report_text(
    results: list[tuple[str, Outcome]], verb: str, suffix: str, expected: str
) -> None:
    assert report_text(report(*results), verb, suffix) == expected


def test_report_text_escapes_light_name() -> None:
    text = report_text(report(("*Desk_lamp*", OK)), "Turned on")
    assert "\\*Desk\\_lamp\\*" in text
    assert "*Desk_lamp*" not in text


def test_report_text_breaks_mentions() -> None:
    text = report_text(report(("Desk", OK), ("@everyone", FAILED)), "Turned on")
    assert "@everyone" not in text


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            app_commands.CheckFailure("x"),
            "You are not allowed to use this command.",
            id="check-failure",
        ),
        pytest.param(BridgeUnavailable(), "Can't reach the Hue bridge.", id="bridge-unavailable"),
        pytest.param(
            wrapped(BridgeUnavailable()),
            "Can't reach the Hue bridge.",
            id="wrapped-bridge-unavailable",
        ),
        pytest.param(
            NotFound('No light named "my_lamp".'),
            'No light named "my\\_lamp".',
            id="not-found-escaped",
        ),
        pytest.param(ValueError("boom"), None, id="unexpected"),
    ],
)
def test_error_text(error: Exception, expected: str | None) -> None:
    assert error_text(error) == expected


@pytest.mark.parametrize(
    ("view", "expected"),
    [
        (SettingsView(), "Reset scene: none\nDaytime confirmation: off\nExcluded from /on: none"),
        (
            SettingsView(daytime_confirm=True),
            "Reset scene: none\nDaytime confirmation: on\nExcluded from /on: none",
        ),
        (
            SettingsView(reset_scene_id=1, reset_scene_name="Evening"),
            "Reset scene: **Evening**\nDaytime confirmation: off\nExcluded from /on: none",
        ),
        (
            SettingsView(reset_scene_id=1, reset_scene_name="*Night*", daytime_confirm=True),
            "Reset scene: **\*Night\***\nDaytime confirmation: on\nExcluded from /on: none",
        ),
        (
            SettingsView(on_exclude=("id-hall", "id-desk")),
            "Reset scene: none\nDaytime confirmation: off\nExcluded from /on: Desk, Hallway",
        ),
    ],
)
def test_settings_text(view: SettingsView, expected: str) -> None:
    assert settings_text(view, LIGHT_NAMES) == expected


@pytest.mark.parametrize(
    ("excluded", "names", "expected"),
    [
        pytest.param((), LIGHT_NAMES, "none", id="none"),
        pytest.param(("id-desk", "id-hall"), LIGHT_NAMES, "Desk, Hallway", id="sorted"),
        pytest.param(("id-star",), LIGHT_NAMES, "\\*Star\\*", id="escaped"),
        pytest.param(
            ("id-desk", "id-gone"), LIGHT_NAMES, "Desk (+1 not controllable)", id="one-hidden"
        ),
        pytest.param(("id-gone",), LIGHT_NAMES, "none (+1 not controllable)", id="only-hidden"),
        pytest.param(("id-desk",), None, "1 light (bridge unreachable)", id="bridge-down-one"),
        pytest.param(
            ("id-desk", "id-hall"), None, "2 lights (bridge unreachable)", id="bridge-down-two"
        ),
    ],
)
def test_excluded_text(
    excluded: tuple[str, ...], names: dict[str, str] | None, expected: str
) -> None:
    assert excluded_text(excluded, names) == expected


@pytest.mark.parametrize(
    ("lights", "bare"),
    [(None, True), ("", True), (" , ,", True), ("Desk", False), (" desk, ", False)],
)
def test_is_bare(lights: str | None, bare: bool) -> None:
    assert is_bare(lights) is bare
