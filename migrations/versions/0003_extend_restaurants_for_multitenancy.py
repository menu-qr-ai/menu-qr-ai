"""extend restaurants for multitenancy

Revision ID: 0003_extend_restaurants_for_multitenancy
Revises: 0002_add_analytics_events
Create Date: 2026-06-28
"""

from __future__ import annotations

import re
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "0003_extend_restaurants_for_multitenancy"
down_revision = "0002_add_analytics_events"
branch_labels = None
depends_on = None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "restaurant"


def _widen_alembic_revision_column() -> None:
    # Alembic defaults version_num to VARCHAR(32), while this revision and
    # several later historical identifiers are longer. SQLite does not enforce
    # that limit, but PostgreSQL does, so widen it before Alembic records 0003.
    if op.get_context().dialect.name == "sqlite":
        with op.batch_alter_table("alembic_version") as batch_op:
            batch_op.alter_column(
                "version_num",
                existing_type=sa.String(length=32),
                type_=sa.String(length=255),
                existing_nullable=False,
            )
        return
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=255),
        existing_nullable=False,
    )


def upgrade() -> None:
    _widen_alembic_revision_column()
    op.add_column("restaurants", sa.Column("slug", sa.String(), nullable=True))
    op.add_column("restaurants", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("restaurants", sa.Column("logo_url", sa.String(), nullable=True))
    op.add_column("restaurants", sa.Column("cover_image_url", sa.String(), nullable=True))
    op.add_column("restaurants", sa.Column("primary_color", sa.String(), nullable=True))
    op.add_column("restaurants", sa.Column("accent_color", sa.String(), nullable=True))
    op.add_column("restaurants", sa.Column("phone", sa.String(), nullable=True))
    op.add_column("restaurants", sa.Column("email", sa.String(), nullable=True))
    op.add_column("restaurants", sa.Column("address", sa.String(), nullable=True))
    op.add_column("restaurants", sa.Column("city", sa.String(), nullable=True))
    op.add_column("restaurants", sa.Column("country", sa.String(), nullable=True))
    op.add_column("restaurants", sa.Column("currency", sa.String(), nullable=False, server_default="EUR"))
    op.add_column("restaurants", sa.Column("default_language", sa.String(), nullable=False, server_default="es"))
    op.add_column("restaurants", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("restaurants", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.add_column("restaurants", sa.Column("updated_at", sa.DateTime(), nullable=True))

    bind = op.get_bind()
    restaurants = bind.execute(sa.text("SELECT id, name FROM restaurants ORDER BY id")).fetchall()
    used_slugs: set[str] = set()
    now = datetime.utcnow()
    for restaurant_id, name in restaurants:
        base_slug = _slugify(name or f"restaurant-{restaurant_id}")
        slug = base_slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        used_slugs.add(slug)
        bind.execute(
            sa.text(
                "UPDATE restaurants "
                "SET slug = :slug, created_at = :created_at, updated_at = :updated_at "
                "WHERE id = :restaurant_id"
            ),
            {"slug": slug, "created_at": now, "updated_at": now, "restaurant_id": restaurant_id},
        )

    op.create_index("ix_restaurants_slug", "restaurants", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_restaurants_slug", table_name="restaurants")
    op.drop_column("restaurants", "updated_at")
    op.drop_column("restaurants", "created_at")
    op.drop_column("restaurants", "is_active")
    op.drop_column("restaurants", "default_language")
    op.drop_column("restaurants", "currency")
    op.drop_column("restaurants", "country")
    op.drop_column("restaurants", "city")
    op.drop_column("restaurants", "address")
    op.drop_column("restaurants", "email")
    op.drop_column("restaurants", "phone")
    op.drop_column("restaurants", "accent_color")
    op.drop_column("restaurants", "primary_color")
    op.drop_column("restaurants", "cover_image_url")
    op.drop_column("restaurants", "logo_url")
    op.drop_column("restaurants", "description")
    op.drop_column("restaurants", "slug")
