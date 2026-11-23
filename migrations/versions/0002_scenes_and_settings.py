"""Scenes, their actions, and the bot-wide settings row (brief §5, D13, D18, D19).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 50", name=op.f("ck_scenes_name_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenes")),
    )
    op.create_index(
        "uq_scenes_lower_name", "scenes", [sa.literal_column("lower(name)")], unique=True
    )
    op.create_table(
        "scene_actions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("scene_id", sa.BigInteger(), nullable=False),
        sa.Column("light_id", sa.Text(), nullable=False),
        sa.Column("is_on", sa.Boolean(), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("brightness", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint(
            "color ~ '^(#[0-9a-f]{6}|[0-9]{4}K)$'", name=op.f("ck_scene_actions_color_format")
        ),
        sa.CheckConstraint(
            "brightness BETWEEN 0 AND 100", name=op.f("ck_scene_actions_brightness_range")
        ),
        sa.CheckConstraint(
            "is_on OR (color IS NULL AND brightness IS NULL)",
            name=op.f("ck_scene_actions_off_is_plain"),
        ),
        sa.ForeignKeyConstraint(
            ["scene_id"],
            ["scenes.id"],
            name=op.f("fk_scene_actions_scene_id_scenes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scene_actions")),
        sa.UniqueConstraint(
            "scene_id", "light_id", name=op.f("uq_scene_actions_scene_id_light_id")
        ),
    )
    op.create_table(
        "bot_settings",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("reset_scene_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_bot_settings_single_row")),
        sa.ForeignKeyConstraint(
            ["reset_scene_id"],
            ["scenes.id"],
            name=op.f("fk_bot_settings_reset_scene_id_scenes"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_settings")),
    )
    # D18: the one settings row, with nothing set.
    op.execute("INSERT INTO bot_settings (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("bot_settings")
    op.drop_table("scene_actions")
    op.drop_index("uq_scenes_lower_name", table_name="scenes")
    op.drop_table("scenes")
