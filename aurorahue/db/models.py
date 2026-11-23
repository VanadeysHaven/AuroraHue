"""ORM models: scenes, their actions, and the bot-wide settings row (brief §5).

Every table is registered on `Base.metadata` by importing this module (migrations/env.py does).
Relationships use ``lazy="raise"``: async code must load them explicitly (``selectinload``), so a
forgotten load fails loudly. Child rows are removed by ``ON DELETE CASCADE`` in the database
(``passive_deletes=True``). Timestamps come from the services' `Clock`, not the database.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aurorahue.db.base import Base

__all__ = ["Base", "BotSettings", "Scene", "SceneAction"]

SCENE_NAME_MAX = 50
SETTINGS_ROW_ID = 1


class Scene(Base):
    """A named set of light actions (D13). Global, not per Discord server (D14)."""

    __tablename__ = "scenes"
    __table_args__ = (
        CheckConstraint(f"char_length(name) BETWEEN 1 AND {SCENE_NAME_MAX}", name="name_length"),
        # D13: names are unique, case-insensitive.
        Index("uq_scenes_lower_name", text("lower(name)"), unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger)  # Discord user id
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    actions: Mapped[list["SceneAction"]] = relationship(
        back_populates="scene",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="SceneAction.id",
    )


class SceneAction(Base):
    """What one light does when its scene runs (D13). `light_id` has no FK: lights live on the
    bridge, and an action for a light that's no longer allowed is skipped at run time (D17)."""

    __tablename__ = "scene_actions"
    __table_args__ = (
        UniqueConstraint("scene_id", "light_id"),
        # D9 stored form: '#rrggbb' (lowercase) or '2700K'.
        CheckConstraint(r"color ~ '^(#[0-9a-f]{6}|[0-9]{4}K)$'", name="color_format"),
        CheckConstraint("brightness BETWEEN 0 AND 100", name="brightness_range"),
        # D13: an action that switches a light off has no colour or brightness.
        CheckConstraint("is_on OR (color IS NULL AND brightness IS NULL)", name="off_is_plain"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    scene_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("scenes.id", ondelete="CASCADE"))
    light_id: Mapped[str] = mapped_column(Text)  # CLIP v2 UUID
    is_on: Mapped[bool] = mapped_column(Boolean)
    color: Mapped[str | None] = mapped_column(String(7))
    brightness: Mapped[int | None] = mapped_column(SmallInteger)  # percent (D10)

    scene: Mapped[Scene] = relationship(back_populates="actions", lazy="raise")


class BotSettings(Base):
    """Bot-wide settings (D18): exactly one row, id 1, inserted by migration 0002."""

    __tablename__ = "bot_settings"
    __table_args__ = (CheckConstraint(f"id = {SETTINGS_ROW_ID}", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    # D19: deleting the reset scene clears the setting.
    reset_scene_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("scenes.id", ondelete="SET NULL")
    )
