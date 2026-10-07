"""add menu management fields

Revision ID: 0023_add_menu_management
Revises: 0022_add_customer_qr_ordering_foundation
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_add_menu_management"
down_revision = "0022_add_customer_qr_ordering_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("categories") as batch_op:
        batch_op.add_column(
            sa.Column("display_order", sa.Integer(), nullable=False, server_default="0")
        )

    # Dishes are hidden, never deleted: historical order lines reference them.
    with op.batch_alter_table("dishes") as batch_op:
        batch_op.add_column(
            sa.Column("display_order", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.create_index("ix_dishes_is_active", ["is_active"])


def downgrade() -> None:
    with op.batch_alter_table("dishes") as batch_op:
        batch_op.drop_index("ix_dishes_is_active")
        batch_op.drop_column("is_active")
        batch_op.drop_column("display_order")

    with op.batch_alter_table("categories") as batch_op:
        batch_op.drop_column("display_order")
