"""Which lights the bot may touch (D1, D2). Pure: the file is read in `aurorahue.config`."""

from collections.abc import Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LightAccess(BaseModel):
    """The parsed `configs/lights.json`: a whitelist or a blacklist of CLIP v2 light UUIDs."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    whitelist: bool
    lights: frozenset[UUID] = frozenset()

    def allows(self, light_id: str) -> bool:
        """Whether the bot may touch this light. IDs compare as UUIDs, so case doesn't matter."""
        if not self.lights:
            return True  # D2: an empty list allows every light, whatever `whitelist` says.
        listed = _as_uuid(light_id) in self.lights
        return listed if self.whitelist else not listed

    def unknown(self, bridge_ids: Iterable[str]) -> list[UUID]:
        """Listed IDs that aren't among `bridge_ids` (D3: a warning, not an error), sorted."""
        on_bridge = {_as_uuid(light_id) for light_id in bridge_ids}
        return sorted(self.lights - on_bridge, key=str)

    def describe(self) -> str:
        """Short summary for the startup log ("whitelist, 6 lights")."""
        if not self.lights:
            return "all lights (empty list)"
        count = len(self.lights)
        kind = "whitelist" if self.whitelist else "blacklist"
        return f"{kind}, {count} light{'' if count == 1 else 's'}"


def _as_uuid(light_id: str) -> UUID | None:
    try:
        return UUID(light_id)
    except ValueError:
        return None
