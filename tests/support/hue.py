"""A fake Hue bridge for service tests: no network, records every change."""

from aurorahue.core.errors import BridgeUnavailable
from aurorahue.hue.hue_client import BridgeLight, LightState


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
        on=False,
        brightness=50.0 if dimming else None,
        xy=(0.3, 0.3) if color else None,
        mirek=300 if temperature else None,
        supports_color=color,
        supports_temperature=temperature,
        mirek_range=mirek_range,
        supports_dimming=dimming,
    )


class FakeClient:
    """Stands in for `HueClient`: records every applied state, can fail chosen lights."""

    def __init__(self, lights: list[BridgeLight]) -> None:
        self.lights = lights
        self.applied: list[tuple[str, LightState]] = []
        self.failing: set[str] = set()

    async def list_lights(self) -> list[BridgeLight]:
        return list(self.lights)

    async def apply(self, light_id: str, state: LightState) -> None:
        if light_id in self.failing:
            raise BridgeUnavailable()
        self.applied.append((light_id, state))
