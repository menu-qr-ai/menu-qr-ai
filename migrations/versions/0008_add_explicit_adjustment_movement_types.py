"""add explicit adjustment movement types

Revision ID: 0008_add_explicit_adjustment_movement_types
Revises: 0007_add_inventory_movement_reference
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op

revision = "0008_add_explicit_adjustment_movement_types"
down_revision = "0007_add_inventory_movement_reference"
branch_labels = None
depends_on = None


NEW_ALLOWED_TYPES = "movement_type IN ('IN', 'OUT', 'ADJUSTMENT', 'ADJUSTMENT_POSITIVE', 'ADJUSTMENT_NEGATIVE', 'WASTE')"
OLD_ALLOWED_TYPES = "movement_type IN ('IN', 'OUT', 'ADJUSTMENT', 'WASTE')"


def upgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.drop_constraint("ck_inventory_movements_type_allowed", type_="check")
        batch_op.create_check_constraint("ck_inventory_movements_type_allowed", NEW_ALLOWED_TYPES)


def downgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.drop_constraint("ck_inventory_movements_type_allowed", type_="check")
        batch_op.create_check_constraint("ck_inventory_movements_type_allowed", OLD_ALLOWED_TYPES)
