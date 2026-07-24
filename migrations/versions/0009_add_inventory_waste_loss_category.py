"""add inventory waste loss category

Revision ID: 0009_add_inventory_waste_loss_category
Revises: 0008_add_explicit_adjustment_movement_types
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009_add_inventory_waste_loss_category"
down_revision = "0008_add_explicit_adjustment_movement_types"
branch_labels = None
depends_on = None


ALLOWED_LOSS_CATEGORIES = (
    "loss_category IS NULL OR loss_category IN "
    "('expiration', 'spoilage', 'preparation_error', 'breakage', 'unknown_loss', 'other')"
)


def upgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.add_column(sa.Column("loss_category", sa.String(), nullable=True))
        batch_op.create_check_constraint("ck_inventory_movements_loss_category_allowed", ALLOWED_LOSS_CATEGORIES)


def downgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.drop_constraint("ck_inventory_movements_loss_category_allowed", type_="check")
        batch_op.drop_column("loss_category")
