"""Services wired for integration tests: the test session as a `SessionFactory`, and a fake
bridge with a known set of lights."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from aurorahue.core.access import LightAccess
from aurorahue.services.lights import LightService
from aurorahue.services.model import SessionFactory
from tests.support.clock import FixedClock
from tests.support.hue import FakeClient, make_light

DESK_ID = "0c9f5a1e-1111-4a3b-8c2d-000000000001"  # colour + temperature
HALLWAY_ID = "0c9f5a1e-1111-4a3b-8c2d-000000000002"  # temperature only, mirek 153-454
PORCH_ID = "0c9f5a1e-1111-4a3b-8c2d-000000000003"  # plain white
GARAGE_ID = "0c9f5a1e-1111-4a3b-8c2d-000000000004"  # on the bridge, blacklisted
GONE_ID = "0c9f5a1e-1111-4a3b-8c2d-0000000000ff"  # allowed, but not on the bridge


def session_factory(session: AsyncSession) -> SessionFactory:
    """A `SessionFactory` that hands out the test session (its commits are savepoints)."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield session

    return factory


def home_bridge() -> FakeClient:
    return FakeClient(
        [
            make_light(DESK_ID, "Desk", color=True, temperature=True, mirek_range=(153, 500)),
            make_light(HALLWAY_ID, "Hallway", temperature=True, mirek_range=(153, 454)),
            make_light(PORCH_ID, "Porch"),
            make_light(GARAGE_ID, "Garage", color=True, temperature=True, mirek_range=(153, 500)),
        ]
    )


def light_service(
    bridge: FakeClient, clock: FixedClock, *, blacklist: tuple[str, ...] = (GARAGE_ID,)
) -> LightService:
    """A `LightService` that blocks Garage (and whatever else `blacklist` names)."""
    access = LightAccess(whitelist=False, lights=frozenset(UUID(i) for i in blacklist))
    return LightService(bridge, access, clock)
