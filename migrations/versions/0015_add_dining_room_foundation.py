"""add dining room foundation

Revision ID: 0015_add_dining_room_foundation
Revises: 0014_add_restaurant_memberships
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_add_dining_room_foundation"
down_revision = "0014_add_restaurant_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "restaurant_zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "restaurant_id",
            "name",
            name="uq_restaurant_zones_restaurant_name",
        ),
    )
    op.create_index("ix_restaurant_zones_id", "restaurant_zones", ["id"])
    op.create_index(
        "ix_restaurant_zones_restaurant_id",
        "restaurant_zones",
        ["restaurant_id"],
    )
    op.create_index(
        "ix_restaurant_zones_is_active",
        "restaurant_zones",
        ["is_active"],
    )

    op.create_table(
        "restaurant_tables",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("zone_id", sa.Integer(), sa.ForeignKey("restaurant_zones.id"), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            "capacity > 0",
            name="ck_restaurant_tables_capacity_positive",
        ),
        sa.UniqueConstraint(
            "restaurant_id",
            "code",
            name="uq_restaurant_tables_restaurant_code",
        ),
    )
    op.create_index("ix_restaurant_tables_id", "restaurant_tables", ["id"])
    op.create_index(
        "ix_restaurant_tables_restaurant_id",
        "restaurant_tables",
        ["restaurant_id"],
    )
    op.create_index("ix_restaurant_tables_zone_id", "restaurant_tables", ["zone_id"])
    op.create_index(
        "ix_restaurant_tables_is_active",
        "restaurant_tables",
        ["is_active"],
    )

    op.create_table(
        "service_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("restaurant_tables.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("opened_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("guest_count", sa.Integer(), nullable=True),
        sa.Column("opened_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("closed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            "status IN ('open', 'closed', 'cancelled')",
            name="ck_service_sessions_status",
        ),
        sa.CheckConstraint(
            "guest_count IS NULL OR guest_count > 0",
            name="ck_service_sessions_guest_count_positive",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND closed_at IS NULL) OR "
            "(status IN ('closed', 'cancelled') AND closed_at IS NOT NULL)",
            name="ck_service_sessions_closed_at",
        ),
    )
    op.create_index("ix_service_sessions_id", "service_sessions", ["id"])
    op.create_index(
        "ix_service_sessions_restaurant_id",
        "service_sessions",
        ["restaurant_id"],
    )
    op.create_index("ix_service_sessions_table_id", "service_sessions", ["table_id"])
    op.create_index("ix_service_sessions_status", "service_sessions", ["status"])
    op.create_index("ix_service_sessions_opened_at", "service_sessions", ["opened_at"])
    op.create_index(
        "ix_service_sessions_opened_by_user_id",
        "service_sessions",
        ["opened_by_user_id"],
    )
    op.create_index(
        "ix_service_sessions_closed_by_user_id",
        "service_sessions",
        ["closed_by_user_id"],
    )
    op.create_index(
        "uq_service_sessions_open_table",
        "service_sessions",
        ["table_id"],
        unique=True,
        sqlite_where=sa.text("status = 'open'"),
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_table("service_sessions")
    op.drop_table("restaurant_tables")
    op.drop_table("restaurant_zones")
