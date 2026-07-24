"""add payment foundation

Revision ID: 0021_add_payment_foundation
Revises: 0020_add_service_session_settlement
Create Date: 2026-07-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_add_payment_foundation"
down_revision = "0020_add_service_session_settlement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("settlement_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column(
            "amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("reference", sa.String(length=128), nullable=True),
        sa.Column(
            "idempotency_key",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("paid_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status = 'completed'",
            name="ck_payments_status",
        ),
        sa.CheckConstraint(
            "method IN ('cash', 'card', 'other')",
            name="ck_payments_method",
        ),
        sa.CheckConstraint(
            "amount > 0 AND amount <= 9999999999.99",
            name="ck_payments_amount_range",
        ),
        sa.CheckConstraint(
            "length(currency) >= 3 AND length(currency) <= 8",
            name="ck_payments_currency_length",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) > 0",
            name="ck_payments_idempotency_key_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["restaurants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["settlement_id"],
            ["service_session_settlements.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "restaurant_id",
            "idempotency_key",
            name="uq_payments_restaurant_idempotency_key",
        ),
    )
    op.create_index(
        "ix_payments_id",
        "payments",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_payments_restaurant_id",
        "payments",
        ["restaurant_id"],
        unique=False,
    )
    op.create_index(
        "ix_payments_settlement_id",
        "payments",
        ["settlement_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("payments")
