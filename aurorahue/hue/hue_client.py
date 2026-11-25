"""The Hue bridge over CLIP v2: list lights and change one light at a time. No access rules here;
those live in `aurorahue.services.lights`."""

import logging
from dataclasses import dataclass
from typing import Any

import httpx2

from aurorahue.core.errors import BridgeUnavailable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BridgeLight:
    """One light as the bridge reports it."""

    id: str
    name: str
    on: bool
    brightness: float | None  # 0-100; 0 is the lowest glow, not off
    xy: tuple[float, float] | None
    mirek: int | None  # only while the light is in white-temperature mode (`mirek_valid`)
    supports_color: bool
    supports_temperature: bool
    mirek_range: tuple[int, int] | None  # `color_temperature.mirek_schema`
    supports_dimming: bool


@dataclass(frozen=True)
class LightState:
    """What to send to one light. Fields left as None are left out of the request; `on=None`
    keeps the light on or off as it is (D28)."""

    on: bool | None
    xy: tuple[float, float] | None = None
    mirek: int | None = None
    brightness: float | None = None

    def __post_init__(self) -> None:
        if self.xy is not None and self.mirek is not None:
            raise ValueError("a light state holds either xy or mirek, not both")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.on is not None:
            payload["on"] = {"on": self.on}
        if self.brightness is not None:
            payload["dimming"] = {"brightness": self.brightness}
        if self.xy is not None:
            payload["color"] = {"xy": {"x": self.xy[0], "y": self.xy[1]}}
        if self.mirek is not None:
            payload["color_temperature"] = {"mirek": self.mirek}
        return payload


class HueClient:
    def __init__(self, bridge_ip: str, app_key: str) -> None:
        self._client = httpx2.AsyncClient(
            base_url=f"https://{bridge_ip}/clip/v2",
            headers={"hue-application-key": app_key},
            verify=False,
            timeout=10.0,
        )

    async def list_lights(self) -> list[BridgeLight]:
        """Every light on the bridge, in the bridge's order."""
        try:
            resp = await self._client.get("/resource/light")
            resp.raise_for_status()
            return [_parse_light(item) for item in resp.json()["data"]]
        except httpx2.HTTPError as exc:
            log.warning("Listing lights failed: %s", exc)
            raise BridgeUnavailable() from exc
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("Unexpected light list from the bridge: %r", exc)
            raise BridgeUnavailable("The Hue bridge sent an unexpected answer.") from exc

    async def apply(self, light_id: str, state: LightState) -> None:
        """Send one PUT for one light. The bridge takes ~10 light commands/s: call sequentially."""
        try:
            resp = await self._client.put(f"/resource/light/{light_id}", json=state.to_payload())
            resp.raise_for_status()
        except httpx2.HTTPError as exc:
            log.warning("Changing light %s failed: %s", light_id, exc)
            raise BridgeUnavailable() from exc

    async def aclose(self) -> None:
        await self._client.aclose()


def _parse_light(item: dict[str, Any]) -> BridgeLight:
    dimming = item.get("dimming")
    color = item.get("color")
    temperature = item.get("color_temperature")
    schema = temperature.get("mirek_schema") if temperature else None
    return BridgeLight(
        id=item["id"],
        name=item["metadata"]["name"],
        on=bool(item["on"]["on"]),
        brightness=float(dimming["brightness"]) if dimming else None,
        xy=(float(color["xy"]["x"]), float(color["xy"]["y"])) if color else None,
        mirek=(
            int(temperature["mirek"])
            if temperature and temperature.get("mirek_valid") and temperature.get("mirek")
            else None
        ),
        supports_color=color is not None,
        supports_temperature=temperature is not None,
        mirek_range=(
            (int(schema["mirek_minimum"]), int(schema["mirek_maximum"])) if schema else None
        ),
        supports_dimming=dimming is not None,
    )
