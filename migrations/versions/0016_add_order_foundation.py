"""add order foundation

Revision ID: 0016_add_order_foundation
Revises: 0015_add_dining_room_foundation
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_add_order_foundation"
down_revision = "0015_add_dining_room_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column(
            "service_session_id",
            sa.Integer(),
            sa.ForeignKey("service_sessions.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'cancelled', 'completed')",
            name="ck_orders_status",
        ),
        sa.UniqueConstraint(
            "restaurant_id",
            "idempotency_key",
            name="uq_orders_restaurant_idempotency_key",
        ),
    )
    op.create_index("ix_orders_id", "orders", ["id"])
    op.create_index("ix_orders_restaurant_id", "orders", ["restaurant_id"])
    op.create_index("ix_orders_service_session_id", "orders", ["service_session_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_created_by_user_id", "orders", ["created_by_user_id"])

    op.create_table(
        "order_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("dish_id", sa.Integer(), sa.ForeignKey("dishes.id"), nullable=False),
        sa.Column("dish_name", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("quantity > 0", name="ck_order_lines_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_order_lines_unit_price_nonnegative"),
        sa.UniqueConstraint(
            "order_id",
            "idempotency_key",
            name="uq_order_lines_order_idempotency_key",
        ),
    )
    op.create_index("ix_order_lines_id", "order_lines", ["id"])
    op.create_index("ix_order_lines_restaurant_id", "order_lines", ["restaurant_id"])
    op.create_index("ix_order_lines_order_id", "order_lines", ["order_id"])
    op.create_index("ix_order_lines_dish_id", "order_lines", ["dish_id"])


def downgrade() -> None:
    op.drop_table("order_lines")
    op.drop_table("orders")
