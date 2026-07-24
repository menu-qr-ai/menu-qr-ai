"""add kitchen ticket foundation

Revision ID: 0017_add_kitchen_ticket_foundation
Revises: 0016_add_order_foundation
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0017_add_kitchen_ticket_foundation"
down_revision = "0016_add_order_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kitchen_tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column(
            "service_session_id",
            sa.Integer(),
            sa.ForeignKey("service_sessions.id"),
            nullable=False,
        ),
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("restaurant_tables.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ready_at", sa.DateTime(), nullable=True),
        sa.Column("served_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            "status IN ('pending', 'preparing', 'ready', 'served', 'cancelled')",
            name="ck_kitchen_tickets_status",
        ),
        sa.UniqueConstraint("order_id", name="uq_kitchen_tickets_order_id"),
    )
    op.create_index("ix_kitchen_tickets_id", "kitchen_tickets", ["id"])
    op.create_index("ix_kitchen_tickets_restaurant_id", "kitchen_tickets", ["restaurant_id"])
    op.create_index("ix_kitchen_tickets_order_id", "kitchen_tickets", ["order_id"])
    op.create_index(
        "ix_kitchen_tickets_service_session_id",
        "kitchen_tickets",
        ["service_session_id"],
    )
    op.create_index("ix_kitchen_tickets_table_id", "kitchen_tickets", ["table_id"])
    op.create_index("ix_kitchen_tickets_status", "kitchen_tickets", ["status"])
    op.create_index(
        "ix_kitchen_tickets_created_by_user_id",
        "kitchen_tickets",
        ["created_by_user_id"],
    )
    op.create_index("ix_kitchen_tickets_created_at", "kitchen_tickets", ["created_at"])

    op.create_table(
        "kitchen_ticket_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column(
            "kitchen_ticket_id",
            sa.Integer(),
            sa.ForeignKey("kitchen_tickets.id"),
            nullable=False,
        ),
        sa.Column("order_line_id", sa.Integer(), sa.ForeignKey("order_lines.id"), nullable=False),
        sa.Column("dish_id", sa.Integer(), sa.ForeignKey("dishes.id"), nullable=False),
        sa.Column("dish_name", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ready_at", sa.DateTime(), nullable=True),
        sa.Column("served_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            "status IN ('pending', 'preparing', 'ready', 'served', 'cancelled')",
            name="ck_kitchen_ticket_lines_status",
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_kitchen_ticket_lines_quantity_positive",
        ),
        sa.UniqueConstraint(
            "order_line_id",
            name="uq_kitchen_ticket_lines_order_line_id",
        ),
    )
    op.create_index("ix_kitchen_ticket_lines_id", "kitchen_ticket_lines", ["id"])
    op.create_index(
        "ix_kitchen_ticket_lines_restaurant_id",
        "kitchen_ticket_lines",
        ["restaurant_id"],
    )
    op.create_index(
        "ix_kitchen_ticket_lines_kitchen_ticket_id",
        "kitchen_ticket_lines",
        ["kitchen_ticket_id"],
    )
    op.create_index(
        "ix_kitchen_ticket_lines_order_line_id",
        "kitchen_ticket_lines",
        ["order_line_id"],
    )
    op.create_index("ix_kitchen_ticket_lines_dish_id", "kitchen_ticket_lines", ["dish_id"])
    op.create_index("ix_kitchen_ticket_lines_status", "kitchen_ticket_lines", ["status"])


def downgrade() -> None:
    op.drop_table("kitchen_ticket_lines")
    op.drop_table("kitchen_tickets")
