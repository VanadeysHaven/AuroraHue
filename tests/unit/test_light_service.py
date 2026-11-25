"""Unit tests for `LightService`: resolving names, applying states, the light list cache.

The bridge is replaced by `FakeClient`, so nothing here touches the network.
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from aurorahue.core.access import LightAccess
from aurorahue.core.color import Color, Hex, Kelvin
from aurorahue.core.errors import BridgeUnavailable, InvalidInput, NotFound
from aurorahue.hue.hue_client import BridgeLight, LightState
from aurorahue.services.lights import LightRequest, LightService, Outcome, on_targets
from tests.support.clock import FixedClock

DESK_ID = "0c9f5a1e-1111-4a3b-8c2d-000000000001"
HALLWAY_ID = "0c9f5a1e-1111-4a3b-8c2d-000000000002"
PORCH_ID = "0c9f5a1e-1111-4a3b-8c2d-000000000003"
GARAGE_ID = "0c9f5a1e-1111-4a3b-8c2d-000000000004"
UNKNOWN_ID = "0c9f5a1e-1111-4a3b-8c2d-0000000000ff"
START = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
COLOR_KEYS = ("color", "color_temperature")


def make_light(
    light_id: str,
    name: str,
    *,
    color: bool = False,
    temperature: bool = False,
    mirek_range: tuple[int, int] | None = None,
    dimming: bool = True,
) -> BridgeLight:
    return BridgeLight(
        id=light_id,
        name=name,
        on=True,
        brightness=50.0 if dimming else None,
        xy=(0.3, 0.3) if color else None,
        mirek=300 if temperature else None,
        supports_color=color,
        supports_temperature=temperature,
        mirek_range=mirek_range,
        supports_dimming=dimming,
    )


class FakeClient:
    """Stands in for `HueClient`: records every PUT, can fail chosen lights."""

    def __init__(self, lights: list[BridgeLight]) -> None:
        self.lights = lights
        self.list_calls = 0
        self.puts: list[tuple[str, dict[str, Any]]] = []
        self.failing: set[str] = set()

    async def list_lights(self) -> list[BridgeLight]:
        self.list_calls += 1
        return list(self.lights)

    async def apply(self, light_id: str, state: LightState) -> None:
        if light_id in self.failing:
            raise BridgeUnavailable()
        self.puts.append((light_id, state.to_payload()))


@dataclass
class Env:
    service: LightService
    client: FakeClient
    clock: FixedClock

    def payloads(self) -> dict[str, dict[str, Any]]:
        """The last payload sent to each light."""
        return {light_id: payload for light_id, payload in self.client.puts}


def make_env() -> Env:
    client = FakeClient(
        [
            make_light(
                DESK_ID,
                "Desk",
                color=True,
                temperature=True,
                mirek_range=(153, 500),
            ),
            make_light(HALLWAY_ID, "Hallway", temperature=True, mirek_range=(153, 454)),
            make_light(PORCH_ID, "Porch"),
            make_light(
                GARAGE_ID,
                "Garage",
                color=True,
                temperature=True,
                mirek_range=(153, 500),
            ),
        ]
    )
    access = LightAccess(whitelist=False, lights=frozenset({UUID(GARAGE_ID)}))
    clock = FixedClock(START)
    return Env(LightService(client, access, clock), client, clock)


@pytest.fixture
def env() -> Env:
    return make_env()


def assert_no_both_colour_keys(payload: dict[str, Any]) -> None:
    assert not ("color" in payload and "color_temperature" in payload), payload


# resolve


@pytest.mark.parametrize("text", [None, ""])
async def test_resolve_empty_returns_all_allowed_sorted(env: Env, text: str | None) -> None:
    lights = await env.service.resolve(text)

    assert [light.name for light in lights] == ["Desk", "Hallway", "Porch"]


@pytest.mark.parametrize("text", ["desk, Hallway", "DESK,hallway", " desk ,  HALLWAY "])
async def test_resolve_names_ignore_case_and_spacing(env: Env, text: str) -> None:
    lights = await env.service.resolve(text)

    assert sorted(light.name for light in lights) == ["Desk", "Hallway"]


async def test_resolve_duplicate_names_collapse(env: Env) -> None:
    lights = await env.service.resolve("desk, Desk, DESK")

    assert [light.name for light in lights] == ["Desk"]


@pytest.mark.parametrize(
    ("text", "bad_names"),
    [("desk, nonsense", ["nonsense"]), ("foo, bar", ["foo", "bar"])],
)
async def test_resolve_unknown_names_raise_not_found(
    env: Env, text: str, bad_names: list[str]
) -> None:
    with pytest.raises(NotFound) as info:
        await env.service.resolve(text)

    for bad in bad_names:
        assert bad in info.value.message


async def test_resolve_disallowed_light_counts_as_unknown(env: Env) -> None:
    with pytest.raises(NotFound) as info:
        await env.service.resolve("garage")

    assert "garage" in info.value.message


# apply


async def test_apply_disallowed_id_is_skipped_and_others_still_apply(env: Env) -> None:
    report = await env.service.apply([GARAGE_ID, DESK_ID], LightRequest(on=True))

    outcomes = {result.light_id: result.outcome for result in report.results}
    assert outcomes[GARAGE_ID] is Outcome.NOT_ALLOWED
    assert outcomes[DESK_ID] is Outcome.OK
    assert [light_id for light_id, _ in env.client.puts] == [DESK_ID]


async def test_apply_unknown_id_is_missing_and_not_sent(env: Env) -> None:
    report = await env.service.apply([UNKNOWN_ID, DESK_ID], LightRequest(on=True))

    outcomes = {result.light_id: result.outcome for result in report.results}
    assert outcomes[UNKNOWN_ID] is Outcome.MISSING
    assert [light_id for light_id, _ in env.client.puts] == [DESK_ID]


@pytest.mark.parametrize(
    ("light_id", "color"),
    [(HALLWAY_ID, Hex("#ff8800")), (PORCH_ID, Kelvin(2700))],
    ids=["hex-on-white-only", "kelvin-on-plain-white"],
)
async def test_colour_the_light_cannot_show_is_skipped(
    env: Env, light_id: str, color: Color
) -> None:
    report = await env.service.apply([light_id], LightRequest(on=True, color=color))

    assert report.results[0].outcome is Outcome.COLOR_SKIPPED
    payload = env.payloads()[light_id]
    assert not any(key in payload for key in COLOR_KEYS)
    assert payload["on"] == {"on": True}
    assert_no_both_colour_keys(payload)


async def test_kelvin_on_ambiance_light_sets_mirek(env: Env) -> None:
    report = await env.service.apply([HALLWAY_ID], LightRequest(on=True, color=Kelvin(2700)))

    assert report.results[0].outcome is Outcome.OK
    payload = env.payloads()[HALLWAY_ID]
    assert payload["color_temperature"] == {"mirek": 370}
    assert_no_both_colour_keys(payload)


async def test_kelvin_below_light_range_is_clamped(env: Env) -> None:
    await env.service.apply([HALLWAY_ID], LightRequest(on=True, color=Kelvin(2000)))

    assert env.payloads()[HALLWAY_ID]["color_temperature"] == {"mirek": 454}


async def test_hex_on_full_colour_light_sets_xy(env: Env) -> None:
    report = await env.service.apply([DESK_ID], LightRequest(on=True, color=Hex("#ff8800")))

    assert report.results[0].outcome is Outcome.OK
    payload = env.payloads()[DESK_ID]
    assert "xy" in payload["color"]
    assert "color_temperature" not in payload
    assert_no_both_colour_keys(payload)


async def test_brightness_is_sent_as_percent(env: Env) -> None:
    await env.service.apply([DESK_ID, HALLWAY_ID, PORCH_ID], LightRequest(on=True, brightness=40))

    payloads = env.payloads()
    assert len(payloads) == 3
    for payload in payloads.values():
        assert payload["dimming"] == {"brightness": 40.0}
        assert_no_both_colour_keys(payload)


async def test_switching_off_sends_only_on_false(env: Env) -> None:
    await env.service.apply([DESK_ID, HALLWAY_ID, PORCH_ID], LightRequest(on=False))

    payloads = env.payloads()
    assert len(payloads) == 3
    for payload in payloads.values():
        assert payload == {"on": {"on": False}}


async def test_failing_light_does_not_stop_the_others(env: Env) -> None:
    env.client.failing = {DESK_ID}

    report = await env.service.apply([DESK_ID, HALLWAY_ID, PORCH_ID], LightRequest(on=True))

    outcomes = {result.light_id: result.outcome for result in report.results}
    assert outcomes[DESK_ID] is Outcome.FAILED
    assert outcomes[HALLWAY_ID] is Outcome.OK
    assert outcomes[PORCH_ID] is Outcome.OK
    assert [light_id for light_id, _ in env.client.puts] == [HALLWAY_ID, PORCH_ID]
    assert report.changed == 2


async def test_per_light_requests_send_their_own_state(env: Env) -> None:
    await env.service.apply(
        [DESK_ID, HALLWAY_ID],
        {DESK_ID: LightRequest(on=True), HALLWAY_ID: LightRequest(on=False)},
    )

    payloads = env.payloads()
    assert payloads[DESK_ID] == {"on": {"on": True}}
    assert payloads[HALLWAY_ID] == {"on": {"on": False}}


# cache


async def test_allowed_list_is_cached_for_sixty_seconds(env: Env) -> None:
    await env.service.allowed()
    assert env.client.list_calls == 1

    env.clock.advance(timedelta(seconds=59))
    await env.service.allowed()
    assert env.client.list_calls == 1

    env.clock.advance(timedelta(seconds=1))
    await env.service.allowed()
    assert env.client.list_calls == 2


async def test_fresh_allowed_always_fetches(env: Env) -> None:
    await env.service.allowed()
    await env.service.allowed(fresh=True)
    await env.service.allowed(fresh=True)

    assert env.client.list_calls == 3


# lights that are on change now; off lights queue (D28, D35-D38)


def switch_off(env: Env, *light_ids: str) -> None:
    env.client.lights = [
        replace(light, on=False) if light.id in light_ids else light for light in env.client.lights
    ]


def switch_on(env: Env, *light_ids: str) -> None:
    env.client.lights = [
        replace(light, on=True) if light.id in light_ids else light for light in env.client.lights
    ]


def test_request_keeping_on_off_needs_colour_or_brightness() -> None:
    with pytest.raises(ValueError):
        LightRequest(on=None)


def test_state_keeping_on_off_leaves_on_out_of_payload() -> None:
    assert LightState(on=None, brightness=50.0).to_payload() == {"dimming": {"brightness": 50.0}}


async def test_keep_on_off_changes_a_light_that_is_on_without_on(env: Env) -> None:
    report = await env.service.apply([DESK_ID], LightRequest(on=None, color=Hex("#ff8800")))

    assert report.results[0].outcome is Outcome.OK
    payload = env.payloads()[DESK_ID]
    assert "on" not in payload
    assert "xy" in payload["color"]


async def test_keep_on_off_queues_for_a_light_that_is_off(env: Env) -> None:
    switch_off(env, DESK_ID)

    report = await env.service.apply([DESK_ID], LightRequest(on=None, brightness=30))

    assert report.results[0].outcome is Outcome.QUEUED
    assert report.changed == 0
    assert env.client.puts == []


async def test_keep_on_off_mixed_changes_the_lit_light_and_queues_the_other(env: Env) -> None:
    switch_off(env, HALLWAY_ID)

    report = await env.service.apply([DESK_ID, HALLWAY_ID], LightRequest(on=None, brightness=30))

    outcomes = {result.light_id: result.outcome for result in report.results}
    assert outcomes == {DESK_ID: Outcome.OK, HALLWAY_ID: Outcome.QUEUED}
    assert [light_id for light_id, _ in env.client.puts] == [DESK_ID]
    assert report.changed == 1


async def test_keep_on_off_colour_the_light_cannot_show_is_still_skipped(env: Env) -> None:
    report = await env.service.apply([HALLWAY_ID], LightRequest(on=None, color=Hex("#ff8800")))

    assert report.results[0].outcome is Outcome.COLOR_SKIPPED


async def test_switching_on_still_switches_off_lights_on(env: Env) -> None:
    switch_off(env, DESK_ID)

    report = await env.service.apply([DESK_ID], LightRequest(on=True, brightness=30))

    assert report.results[0].outcome is Outcome.OK
    assert env.payloads()[DESK_ID]["on"] == {"on": True}


async def test_off_light_with_nothing_it_can_show_queues_nothing(env: Env) -> None:
    switch_off(env, PORCH_ID)

    report = await env.service.apply([PORCH_ID], LightRequest(on=None, color=Hex("#ff8800")))
    await env.service.apply([PORCH_ID], LightRequest(on=True))

    assert report.results[0].outcome is Outcome.COLOR_SKIPPED
    assert env.payloads()[PORCH_ID] == {"on": {"on": True}}


async def test_fresh_apply_reads_the_bridge(env: Env) -> None:
    await env.service.allowed()
    switch_off(env, DESK_ID)

    report = await env.service.apply([DESK_ID], LightRequest(on=None, brightness=30), fresh=True)

    assert report.results[0].outcome is Outcome.QUEUED
    assert env.client.list_calls == 2


async def test_switching_on_sends_the_queued_change(env: Env) -> None:
    switch_off(env, DESK_ID)
    await env.service.apply([DESK_ID], LightRequest(on=None, color=Hex("#ff8800")))
    await env.service.apply([DESK_ID], LightRequest(on=None, brightness=30))

    await env.service.apply([DESK_ID], LightRequest(on=True))

    payload = env.payloads()[DESK_ID]
    assert payload["on"] == {"on": True}
    assert "xy" in payload["color"]
    assert payload["dimming"] == {"brightness": 30.0}


async def test_newer_queued_value_replaces_the_older(env: Env) -> None:
    switch_off(env, HALLWAY_ID)
    await env.service.apply([HALLWAY_ID], LightRequest(on=None, color=Kelvin(2700)))
    await env.service.apply([HALLWAY_ID], LightRequest(on=None, color=Kelvin(2000)))

    await env.service.apply([HALLWAY_ID], LightRequest(on=True))

    assert env.payloads()[HALLWAY_ID]["color_temperature"] == {"mirek": 454}


async def test_queued_change_is_used_once(env: Env) -> None:
    switch_off(env, DESK_ID)
    await env.service.apply([DESK_ID], LightRequest(on=None, brightness=30))
    await env.service.apply([DESK_ID], LightRequest(on=True))

    await env.service.apply([DESK_ID], LightRequest(on=True))

    assert env.client.puts[-1] == (DESK_ID, {"on": {"on": True}})


async def test_queued_change_expires_after_thirty_minutes(env: Env) -> None:
    switch_off(env, DESK_ID)
    await env.service.apply([DESK_ID], LightRequest(on=None, brightness=30))

    env.clock.advance(timedelta(minutes=30))
    await env.service.apply([DESK_ID], LightRequest(on=True))

    assert env.payloads()[DESK_ID] == {"on": {"on": True}}


async def test_queued_change_kept_just_under_thirty_minutes(env: Env) -> None:
    switch_off(env, DESK_ID)
    await env.service.apply([DESK_ID], LightRequest(on=None, brightness=30))

    env.clock.advance(timedelta(minutes=29, seconds=59))
    await env.service.apply([DESK_ID], LightRequest(on=True))

    assert env.payloads()[DESK_ID]["dimming"] == {"brightness": 30.0}


async def test_newer_queue_starts_the_thirty_minutes_again(env: Env) -> None:
    switch_off(env, DESK_ID)
    await env.service.apply([DESK_ID], LightRequest(on=None, brightness=30))
    env.clock.advance(timedelta(minutes=20))
    await env.service.apply([DESK_ID], LightRequest(on=None, color=Hex("#ff8800")))

    env.clock.advance(timedelta(minutes=20))
    await env.service.apply([DESK_ID], LightRequest(on=True))

    payload = env.payloads()[DESK_ID]
    assert payload["dimming"] == {"brightness": 30.0}
    assert "xy" in payload["color"]


async def test_request_values_win_over_the_queue(env: Env) -> None:
    switch_off(env, DESK_ID)
    await env.service.apply([DESK_ID], LightRequest(on=None, color=Hex("#ff8800"), brightness=30))

    await env.service.apply([DESK_ID], LightRequest(on=True, color=Kelvin(2700)))

    payload = env.payloads()[DESK_ID]
    assert payload["color_temperature"] == {"mirek": 370}
    assert "color" not in payload
    assert payload["dimming"] == {"brightness": 30.0}


async def test_switching_off_keeps_the_queue(env: Env) -> None:
    switch_off(env, DESK_ID)
    await env.service.apply([DESK_ID], LightRequest(on=None, brightness=30))

    await env.service.apply([DESK_ID], LightRequest(on=False))
    await env.service.apply([DESK_ID], LightRequest(on=True))

    assert env.payloads()[DESK_ID]["dimming"] == {"brightness": 30.0}


async def test_change_while_on_drops_the_queue(env: Env) -> None:
    switch_off(env, DESK_ID)
    await env.service.apply([DESK_ID], LightRequest(on=None, brightness=30))
    switch_on(env, DESK_ID)  # e.g. with the Hue app

    await env.service.apply([DESK_ID], LightRequest(on=None, color=Hex("#ff8800")), fresh=True)
    await env.service.apply([DESK_ID], LightRequest(on=True))

    assert env.payloads()[DESK_ID] == {"on": {"on": True}}


async def test_failed_switch_on_keeps_the_queue(env: Env) -> None:
    switch_off(env, DESK_ID)
    await env.service.apply([DESK_ID], LightRequest(on=None, brightness=30))
    env.client.failing = {DESK_ID}
    await env.service.apply([DESK_ID], LightRequest(on=True))

    env.client.failing = set()
    await env.service.apply([DESK_ID], LightRequest(on=True))

    assert env.payloads()[DESK_ID]["dimming"] == {"brightness": 30.0}


async def test_queue_is_per_light(env: Env) -> None:
    switch_off(env, DESK_ID, HALLWAY_ID)
    await env.service.apply([DESK_ID], LightRequest(on=None, brightness=30))

    await env.service.apply([DESK_ID, HALLWAY_ID], LightRequest(on=True))

    payloads = env.payloads()
    assert payloads[DESK_ID]["dimming"] == {"brightness": 30.0}
    assert payloads[HALLWAY_ID] == {"on": {"on": True}}


# on_targets (D31, D33, D34)


def test_on_targets_without_exclusions_is_every_light() -> None:
    lights = make_env().client.lights

    assert on_targets(lights, ()) == [light.id for light in lights]


def test_on_targets_leaves_out_excluded_lights() -> None:
    lights = make_env().client.lights

    assert on_targets(lights, {DESK_ID, PORCH_ID}) == [HALLWAY_ID, GARAGE_ID]


def test_on_targets_ignores_excluded_ids_that_are_not_lights() -> None:
    lights = make_env().client.lights[:2]

    assert on_targets(lights, {UNKNOWN_ID}) == [DESK_ID, HALLWAY_ID]


def test_on_targets_with_every_light_excluded_raises() -> None:
    lights = make_env().client.lights[:2]

    with pytest.raises(InvalidInput) as info:
        on_targets(lights, [DESK_ID, HALLWAY_ID])

    assert "Every light is excluded" in info.value.message


def test_on_targets_with_no_lights_is_empty() -> None:
    assert on_targets([], [DESK_ID]) == []


async def test_keep_on_off_with_nothing_the_light_can_do_sends_nothing(env: Env) -> None:
    report = await env.service.apply([PORCH_ID], LightRequest(on=None, color=Hex("#ff8800")))

    assert report.results[0].outcome is Outcome.COLOR_SKIPPED
    assert env.client.puts == []
