"""Colour and brightness changes waiting for an off light to be switched on by the bot (D35).

In memory only: a restart drops them. Each light's entry lives `PENDING_TTL` after its latest
change; expired entries are dropped when they're next looked at.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from aurorahue.core.clock import Clock
from aurorahue.core.color import Color

PENDING_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class Pending:
    color: Color | None
    brightness: int | None  # percent, 0-100 (D10)
    queued_at: datetime


class PendingChanges:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._entries: dict[str, Pending] = {}

    def queue(self, light_id: str, color: Color | None, brightness: int | None) -> None:
        """D37: a newer value replaces the queued one per field; the 30 minutes start again."""
        old = self.peek(light_id)
        self._entries[light_id] = Pending(
            color=color if color is not None else (old.color if old else None),
            brightness=brightness if brightness is not None else (old.brightness if old else None),
            queued_at=self._clock.now(),
        )

    def peek(self, light_id: str) -> Pending | None:
        entry = self._entries.get(light_id)
        if entry is not None and self._clock.now() - entry.queued_at >= PENDING_TTL:
            del self._entries[light_id]
            return None
        return entry

    def take(self, light_id: str) -> Pending | None:
        """The live entry for the light, removed from the queue."""
        entry = self.peek(light_id)
        self._entries.pop(light_id, None)
        return entry

    def drop(self, light_id: str) -> None:
        self._entries.pop(light_id, None)
