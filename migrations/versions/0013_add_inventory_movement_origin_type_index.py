"""add inventory movement origin type index

Revision ID: 0013_add_inventory_movement_origin_type_index
Revises: 0012_add_inventory_movement_wac_trace
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op

revision = "0013_add_inventory_movement_origin_type_index"
down_revision = "0012_add_inventory_movement_wac_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_inventory_movements_origin_type", "inventory_movements", ["origin_type"])


def downgrade() -> None:
    op.drop_index("ix_inventory_movements_origin_type", table_name="inventory_movements")
