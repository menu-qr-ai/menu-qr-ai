"""add analytics events

Revision ID: 0002_add_analytics_events
Revises: 0001_add_saas_tables
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_add_analytics_events"
down_revision = "0001_add_saas_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("dish_id", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_analytics_events_restaurant_id", "analytics_events", ["restaurant_id"])
    op.create_index("ix_analytics_events_event_type", "analytics_events", ["event_type"])
    op.create_index("ix_analytics_events_dish_id", "analytics_events", ["dish_id"])
    op.create_index("ix_analytics_events_language", "analytics_events", ["language"])
    op.create_index("ix_analytics_events_created_at", "analytics_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("analytics_events")
