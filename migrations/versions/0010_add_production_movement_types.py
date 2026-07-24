"""add production movement types

Revision ID: 0010_add_production_movement_types
Revises: 0009_add_inventory_waste_loss_category
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op

revision = "0010_add_production_movement_types"
down_revision = "0009_add_inventory_waste_loss_category"
branch_labels = None
depends_on = None


NEW_ALLOWED_TYPES = (
    "movement_type IN ('IN', 'OUT', 'ADJUSTMENT', 'ADJUSTMENT_POSITIVE', 'ADJUSTMENT_NEGATIVE', 'WASTE', "
    "'PRODUCTION_CONSUME', 'PRODUCTION_OUTPUT')"
)
OLD_ALLOWED_TYPES = "movement_type IN ('IN', 'OUT', 'ADJUSTMENT', 'ADJUSTMENT_POSITIVE', 'ADJUSTMENT_NEGATIVE', 'WASTE')"


def upgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.drop_constraint("ck_inventory_movements_type_allowed", type_="check")
        batch_op.create_check_constraint("ck_inventory_movements_type_allowed", NEW_ALLOWED_TYPES)


def downgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.drop_constraint("ck_inventory_movements_type_allowed", type_="check")
        batch_op.create_check_constraint("ck_inventory_movements_type_allowed", OLD_ALLOWED_TYPES)
