"""Bot-wide settings (D18): the reset scene that `/reset` runs (D19), the daytime
confirmation (D25) and the lights a bare /on leaves alone (D31)."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from aurorahue.core.errors import NotFound
from aurorahue.db.models import SETTINGS_ROW_ID, BotSettings, Scene
from aurorahue.services.model import SessionFactory, StrictModel


class SettingsView(StrictModel):
    reset_scene_id: int | None = None
    reset_scene_name: str | None = None
    daytime_confirm: bool = False
    on_exclude: tuple[str, ...] = ()  # light IDs (D31)


class SettingsService:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def get_settings(self) -> SettingsView:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(
                        Scene.id,
                        Scene.name,
                        BotSettings.daytime_confirm,
                        BotSettings.on_exclude,
                    )
                    .select_from(BotSettings)
                    .outerjoin(Scene, Scene.id == BotSettings.reset_scene_id)
                    .where(BotSettings.id == SETTINGS_ROW_ID)
                )
            ).first()
            if row is None:
                return SettingsView()
            return SettingsView(
                reset_scene_id=row.id,
                reset_scene_name=row.name,
                daytime_confirm=row.daytime_confirm,
                on_exclude=tuple(row.on_exclude),
            )

    async def set_reset_scene(self, scene_id: int | None) -> SettingsView:
        """Set (or with None, clear) the reset scene. Raises `NotFound` for a deleted scene."""
        async with self._sessions() as session:
            if scene_id is not None and await session.get(Scene, scene_id) is None:
                raise NotFound("That scene doesn't exist any more.")
            await self._upsert(session, reset_scene_id=scene_id)
        return await self.get_settings()

    async def set_daytime_confirm(self, enabled: bool) -> SettingsView:
        """D25: switch the daytime confirmation (D21) on or off."""
        async with self._sessions() as session:
            await self._upsert(session, daytime_confirm=enabled)
        return await self.get_settings()

    async def set_on_exclude(self, light_ids: Sequence[str]) -> SettingsView:
        """D31, D32: replace the lights a bare /on leaves alone; empty clears the list. The
        caller resolves names to allowed lights first (D34)."""
        async with self._sessions() as session:
            await self._upsert(session, on_exclude=sorted(set(light_ids)))
        return await self.get_settings()

    @staticmethod
    async def _upsert(session: AsyncSession, **values: object) -> None:
        # Migration 0002 inserts the row, but don't depend on it still being there.
        stmt = insert(BotSettings).values(id=SETTINGS_ROW_ID, **values)
        stmt = stmt.on_conflict_do_update(index_elements=[BotSettings.id], set_=values)
        await session.execute(stmt)
        await session.commit()
