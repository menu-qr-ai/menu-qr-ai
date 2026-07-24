"""add service session settlement

Revision ID: 0020_add_service_session_settlement
Revises: 0019_add_order_fulfillment_bridge
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_add_service_session_settlement"
down_revision = "0019_add_order_fulfillment_bridge"
branch_labels = None
depends_on = None

MONEY_TYPE = sa.Numeric(precision=12, scale=2)


def upgrade() -> None:
    op.create_table(
        "service_session_settlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
        ),
        sa.Column(
            "service_session_id",
            sa.Integer(),
            sa.ForeignKey("service_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="finalized",
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("subtotal", MONEY_TYPE, nullable=False),
        sa.Column("total", MONEY_TYPE, nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("finalized_at", sa.DateTime(), nullable=False),
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
            "status = 'finalized'",
            name="ck_service_session_settlements_status",
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND subtotal <= 9999999999.99",
            name="ck_service_session_settlements_subtotal_range",
        ),
        sa.CheckConstraint(
            "total >= 0 AND total <= 9999999999.99",
            name="ck_service_session_settlements_total_range",
        ),
        sa.UniqueConstraint(
            "service_session_id",
            name="uq_service_session_settlements_session_id",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_service_session_settlements_idempotency_key",
        ),
    )
    op.create_index(
        "ix_service_session_settlements_id",
        "service_session_settlements",
        ["id"],
    )
    op.create_index(
        "ix_service_session_settlements_restaurant_id",
        "service_session_settlements",
        ["restaurant_id"],
    )
    op.create_index(
        "ix_service_session_settlements_service_session_id",
        "service_session_settlements",
        ["service_session_id"],
    )
    op.create_index(
        "ix_service_session_settlements_status",
        "service_session_settlements",
        ["status"],
    )
    op.create_index(
        "ix_service_session_settlements_created_by_user_id",
        "service_session_settlements",
        ["created_by_user_id"],
    )

    op.create_table(
        "service_session_settlement_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
        ),
        sa.Column(
            "settlement_id",
            sa.Integer(),
            sa.ForeignKey(
                "service_session_settlements.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),
        sa.Column("frozen_total", MONEY_TYPE, nullable=False),
        sa.Column("included_line_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "frozen_total >= 0 AND frozen_total <= 9999999999.99",
            name="ck_service_session_settlement_orders_total_range",
        ),
        sa.CheckConstraint(
            "included_line_count > 0",
            name="ck_service_session_settlement_orders_line_count_positive",
        ),
        sa.UniqueConstraint(
            "order_id",
            name="uq_service_session_settlement_orders_order_id",
        ),
    )
    op.create_index(
        "ix_service_session_settlement_orders_id",
        "service_session_settlement_orders",
        ["id"],
    )
    op.create_index(
        "ix_service_session_settlement_orders_restaurant_id",
        "service_session_settlement_orders",
        ["restaurant_id"],
    )
    op.create_index(
        "ix_service_session_settlement_orders_settlement_id",
        "service_session_settlement_orders",
        ["settlement_id"],
    )
    op.create_index(
        "ix_service_session_settlement_orders_order_id",
        "service_session_settlement_orders",
        ["order_id"],
    )

    op.create_table(
        "service_session_settlement_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
        ),
        sa.Column(
            "settlement_order_id",
            sa.Integer(),
            sa.ForeignKey(
                "service_session_settlement_orders.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "order_line_id",
            sa.Integer(),
            sa.ForeignKey("order_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "fulfillment_line_id",
            sa.Integer(),
            sa.ForeignKey("order_fulfillment_lines.id"),
            nullable=False,
        ),
        sa.Column("dish_name", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", MONEY_TYPE, nullable=False),
        sa.Column("subtotal", MONEY_TYPE, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_service_session_settlement_lines_quantity_positive",
        ),
        sa.CheckConstraint(
            "unit_price >= 0 AND unit_price <= 9999999999.99",
            name="ck_service_session_settlement_lines_unit_price_range",
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND subtotal <= 9999999999.99",
            name="ck_service_session_settlement_lines_subtotal_range",
        ),
        sa.UniqueConstraint(
            "order_line_id",
            name="uq_service_session_settlement_lines_order_line_id",
        ),
        sa.UniqueConstraint(
            "fulfillment_line_id",
            name=(
                "uq_service_session_settlement_lines_fulfillment_line_id"
            ),
        ),
    )
    op.create_index(
        "ix_service_session_settlement_lines_id",
        "service_session_settlement_lines",
        ["id"],
    )
    op.create_index(
        "ix_service_session_settlement_lines_restaurant_id",
        "service_session_settlement_lines",
        ["restaurant_id"],
    )
    op.create_index(
        "ix_service_session_settlement_lines_settlement_order_id",
        "service_session_settlement_lines",
        ["settlement_order_id"],
    )
    op.create_index(
        "ix_service_session_settlement_lines_order_line_id",
        "service_session_settlement_lines",
        ["order_line_id"],
    )
    op.create_index(
        "ix_service_session_settlement_lines_fulfillment_line_id",
        "service_session_settlement_lines",
        ["fulfillment_line_id"],
    )


def downgrade() -> None:
    op.drop_table("service_session_settlement_lines")
    op.drop_table("service_session_settlement_orders")
    op.drop_table("service_session_settlements")
