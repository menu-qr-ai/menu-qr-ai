"""add order fulfillment bridge

Revision ID: 0019_add_order_fulfillment_bridge
Revises: 0018_add_monetary_model_foundation
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_add_order_fulfillment_bridge"
down_revision = "0018_add_monetary_model_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_fulfillments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "executed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_order_fulfillments_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_order_fulfillments_attempt_count_nonnegative",
        ),
        sa.UniqueConstraint(
            "order_id",
            name="uq_order_fulfillments_order_id",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_order_fulfillments_idempotency_key",
        ),
    )
    op.create_index(
        "ix_order_fulfillments_id",
        "order_fulfillments",
        ["id"],
    )
    op.create_index(
        "ix_order_fulfillments_restaurant_id",
        "order_fulfillments",
        ["restaurant_id"],
    )
    op.create_index(
        "ix_order_fulfillments_order_id",
        "order_fulfillments",
        ["order_id"],
    )
    op.create_index(
        "ix_order_fulfillments_status",
        "order_fulfillments",
        ["status"],
    )
    op.create_index(
        "ix_order_fulfillments_executed_by_user_id",
        "order_fulfillments",
        ["executed_by_user_id"],
    )

    op.create_table(
        "order_fulfillment_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
        ),
        sa.Column(
            "fulfillment_id",
            sa.Integer(),
            sa.ForeignKey("order_fulfillments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_line_id",
            sa.Integer(),
            sa.ForeignKey("order_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "kitchen_ticket_line_id",
            sa.Integer(),
            sa.ForeignKey("kitchen_ticket_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "dish_id",
            sa.Integer(),
            sa.ForeignKey("dishes.id"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "operational_reference",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "analytics_event_id",
            sa.Integer(),
            sa.ForeignKey("analytics_events.id"),
            nullable=True,
        ),
        sa.Column("movement_ids", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('processed', 'skipped')",
            name="ck_order_fulfillment_lines_status",
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_order_fulfillment_lines_quantity_positive",
        ),
        sa.UniqueConstraint(
            "order_line_id",
            name="uq_order_fulfillment_lines_order_line_id",
        ),
        sa.UniqueConstraint(
            "kitchen_ticket_line_id",
            name="uq_order_fulfillment_lines_kitchen_ticket_line_id",
        ),
    )
    op.create_index(
        "ix_order_fulfillment_lines_id",
        "order_fulfillment_lines",
        ["id"],
    )
    op.create_index(
        "ix_order_fulfillment_lines_restaurant_id",
        "order_fulfillment_lines",
        ["restaurant_id"],
    )
    op.create_index(
        "ix_order_fulfillment_lines_fulfillment_id",
        "order_fulfillment_lines",
        ["fulfillment_id"],
    )
    op.create_index(
        "ix_order_fulfillment_lines_order_line_id",
        "order_fulfillment_lines",
        ["order_line_id"],
    )
    op.create_index(
        "ix_order_fulfillment_lines_kitchen_ticket_line_id",
        "order_fulfillment_lines",
        ["kitchen_ticket_line_id"],
    )
    op.create_index(
        "ix_order_fulfillment_lines_dish_id",
        "order_fulfillment_lines",
        ["dish_id"],
    )
    op.create_index(
        "ix_order_fulfillment_lines_status",
        "order_fulfillment_lines",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("order_fulfillment_lines")
    op.drop_table("order_fulfillments")
