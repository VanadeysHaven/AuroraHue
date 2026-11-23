"""The light registry: which lights exist and are allowed, resolving names, applying changes.

Every write goes through `LightAccess.allows` here, whatever the caller already checked.
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from aurorahue.core.access import LightAccess
from aurorahue.core.clock import Clock
from aurorahue.core.color import Color, Hex, Kelvin, hex_to_xy, kelvin_to_mirek
from aurorahue.core.errors import BridgeUnavailable, NotFound
from aurorahue.hue.hue_client import BridgeLight, LightState

log = logging.getLogger(__name__)

# D5: the light list is read from the bridge at most once a minute.
CACHE_TTL = timedelta(seconds=60)


class LightClient(Protocol):
    """The part of `HueClient` the service uses (tests pass a fake)."""

    async def list_lights(self) -> list[BridgeLight]: ...

    async def apply(self, light_id: str, state: LightState) -> None: ...


@dataclass(frozen=True)
class LightRequest:
    """What should happen to a light, before its capabilities are known (D13)."""

    on: bool
    color: Color | None = None
    brightness: int | None = None  # percent, 0-100 (D10)

    def __post_init__(self) -> None:
        if not self.on and (self.color is not None or self.brightness is not None):
            raise ValueError("a light switched off takes no colour or brightness")
        if self.brightness is not None and not 0 <= self.brightness <= 100:
            raise ValueError(f"brightness out of range: {self.brightness}")


class Outcome(StrEnum):
    OK = "ok"
    COLOR_SKIPPED = "color_skipped"  # changed, but the light can't show the colour (D11)
    FAILED = "failed"  # the bridge didn't accept the change
    NOT_ALLOWED = "not_allowed"  # the access file doesn't allow it (D17)
    MISSING = "missing"  # not on the bridge (any more) (D17)


@dataclass(frozen=True)
class LightResult:
    light_id: str
    name: str  # the bridge name; the ID when the light isn't on the bridge
    outcome: Outcome


@dataclass(frozen=True)
class ApplyReport:
    results: tuple[LightResult, ...]

    def names(self, *outcomes: Outcome) -> list[str]:
        return [r.name for r in self.results if r.outcome in outcomes]

    @property
    def changed(self) -> int:
        """Lights that took the change (with or without their colour)."""
        return len(self.names(Outcome.OK, Outcome.COLOR_SKIPPED))


class LightService:
    def __init__(self, client: LightClient, access: LightAccess, clock: Clock) -> None:
        self._client = client
        self._access = access
        self._clock = clock
        self._cache: tuple[datetime, list[BridgeLight]] | None = None
        self._lock = asyncio.Lock()

    async def allowed(self, *, fresh: bool = False) -> list[BridgeLight]:
        """The lights the bot may touch, sorted by name. `fresh` skips the cache (current state).

        Raises `BridgeUnavailable`.
        """
        lights = await self._bridge_lights(fresh=fresh)
        allowed = [light for light in lights if self._access.allows(light.id)]
        return sorted(allowed, key=lambda light: (light.name.casefold(), light.id))

    async def resolve(self, text: str | None) -> list[BridgeLight]:
        """Comma-separated light names (any case) -> lights (D6). Empty -> every allowed light.

        Duplicates collapse. A name that matches no allowed light raises `NotFound` naming every
        such name; a disallowed light counts as unknown (D4). Two lights sharing a name both match.
        """
        allowed = await self.allowed()
        names = [part.strip() for part in (text or "").split(",") if part.strip()]
        if not names:
            return allowed

        by_name: dict[str, list[BridgeLight]] = {}
        for light in allowed:
            by_name.setdefault(light.name.casefold(), []).append(light)

        unknown = [name for name in names if name.casefold() not in by_name]
        if unknown:
            unknown = list(dict.fromkeys(unknown))
            listed = ", ".join(f'"{name}"' for name in unknown)
            plural = "s" if len(unknown) > 1 else ""
            raise NotFound(f"No light{plural} named {listed}.")

        found: dict[str, BridgeLight] = {}
        for name in names:
            for light in by_name[name.casefold()]:
                found.setdefault(light.id, light)
        return list(found.values())

    async def apply(
        self, targets: Sequence[str], request: LightRequest | Mapping[str, LightRequest]
    ) -> ApplyReport:
        """Change each target light (IDs), one PUT at a time, and report per light.

        `request` is one request for all targets, or one per target ID. Disallowed and missing
        lights are skipped and reported; a light that fails doesn't stop the others.
        Raises `BridgeUnavailable` only when the light list can't be read.
        """
        lights = {light.id: light for light in await self._bridge_lights()}
        results: list[LightResult] = []
        for light_id in dict.fromkeys(targets):
            light = lights.get(light_id)
            name = light.name if light else light_id
            if not self._access.allows(light_id):
                results.append(LightResult(light_id, name, Outcome.NOT_ALLOWED))
                continue
            if light is None:
                results.append(LightResult(light_id, name, Outcome.MISSING))
                continue

            wanted = request if isinstance(request, LightRequest) else request[light_id]
            state, color_skipped = _state_for(light, wanted)
            try:
                await self._client.apply(light_id, state)
            except BridgeUnavailable:
                results.append(LightResult(light_id, name, Outcome.FAILED))
                continue
            outcome = Outcome.COLOR_SKIPPED if color_skipped else Outcome.OK
            results.append(LightResult(light_id, name, outcome))
        return ApplyReport(tuple(results))

    async def unknown_access_ids(self) -> list[UUID]:
        """IDs in the access file that aren't on the bridge (D3: logged as a warning)."""
        lights = await self._bridge_lights(fresh=True)
        return self._access.unknown(light.id for light in lights)

    async def _bridge_lights(self, *, fresh: bool = False) -> list[BridgeLight]:
        """Every bridge light, allowed or not. Never hand these to Discord unfiltered (D4)."""
        async with self._lock:
            now = self._clock.now()
            if not fresh and self._cache is not None:
                fetched_at, lights = self._cache
                if now - fetched_at < CACHE_TTL:
                    return lights
            lights = await self._client.list_lights()
            self._cache = (now, lights)
            return lights


def _state_for(light: BridgeLight, request: LightRequest) -> tuple[LightState, bool]:
    """Turn a request into what this light can do. Returns the state and whether the colour
    was skipped (D11)."""
    if not request.on:
        return LightState(on=False), False

    brightness = (
        float(request.brightness)
        if request.brightness is not None and light.supports_dimming
        else None
    )
    xy: tuple[float, float] | None = None
    mirek: int | None = None
    color_skipped = False
    match request.color:
        case Hex() as color if light.supports_color:
            xy = hex_to_xy(color)
        case Kelvin() as color if light.supports_temperature:
            mirek = kelvin_to_mirek(color.value, *(light.mirek_range or ()))
        case None:
            pass
        case _:
            color_skipped = True
    return LightState(on=True, xy=xy, mirek=mirek, brightness=brightness), color_skipped
