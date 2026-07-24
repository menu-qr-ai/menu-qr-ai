"""harden inventory movement ledger

Revision ID: 0006_harden_inventory_movement_ledger
Revises: 0005_harden_technical_recipes
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_harden_inventory_movement_ledger"
down_revision = "0005_harden_technical_recipes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.add_column(sa.Column("unit", sa.String(), nullable=False, server_default="unit"))
        batch_op.add_column(sa.Column("reason", sa.String(), nullable=False, server_default="manual"))
        batch_op.add_column(sa.Column("origin_type", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("origin_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("created_by", sa.String(), nullable=True))
        batch_op.create_check_constraint("ck_inventory_movements_quantity_positive", "quantity > 0")
        batch_op.create_check_constraint(
            "ck_inventory_movements_type_allowed",
            "movement_type IN ('IN', 'OUT', 'ADJUSTMENT', 'WASTE')",
        )
        batch_op.create_check_constraint(
            "ck_inventory_movements_unit_allowed",
            "unit IN ('g', 'kg', 'ml', 'l', 'unit')",
        )


def downgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.drop_constraint("ck_inventory_movements_unit_allowed", type_="check")
        batch_op.drop_constraint("ck_inventory_movements_type_allowed", type_="check")
        batch_op.drop_constraint("ck_inventory_movements_quantity_positive", type_="check")
        batch_op.drop_column("created_by")
        batch_op.drop_column("origin_id")
        batch_op.drop_column("origin_type")
        batch_op.drop_column("reason")
        batch_op.drop_column("unit")
