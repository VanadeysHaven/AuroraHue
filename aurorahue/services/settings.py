"""Bot-wide settings (D18). For now one: the reset scene that `/reset` runs (D19)."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from aurorahue.core.errors import NotFound
from aurorahue.db.models import SETTINGS_ROW_ID, BotSettings, Scene
from aurorahue.services.model import SessionFactory, StrictModel


class SettingsView(StrictModel):
    reset_scene_id: int | None = None
    reset_scene_name: str | None = None


class SettingsService:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def get_settings(self) -> SettingsView:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(Scene.id, Scene.name)
                    .select_from(BotSettings)
                    .join(Scene, Scene.id == BotSettings.reset_scene_id)
                    .where(BotSettings.id == SETTINGS_ROW_ID)
                )
            ).first()
            if row is None:
                return SettingsView()
            return SettingsView(reset_scene_id=row.id, reset_scene_name=row.name)

    async def set_reset_scene(self, scene_id: int | None) -> SettingsView:
        """Set (or with None, clear) the reset scene. Raises `NotFound` for a deleted scene."""
        async with self._sessions() as session:
            if scene_id is not None and await session.get(Scene, scene_id) is None:
                raise NotFound("That scene doesn't exist any more.")
            # Upsert: migration 0002 inserts the row, but don't depend on it still being there.
            stmt = insert(BotSettings).values(id=SETTINGS_ROW_ID, reset_scene_id=scene_id)
            stmt = stmt.on_conflict_do_update(
                index_elements=[BotSettings.id], set_={"reset_scene_id": scene_id}
            )
            await session.execute(stmt)
            await session.commit()
        return await self.get_settings()
