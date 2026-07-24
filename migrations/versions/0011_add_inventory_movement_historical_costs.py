"""add inventory movement historical costs

Revision ID: 0011_add_inventory_movement_historical_costs
Revises: 0010_add_production_movement_types
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_add_inventory_movement_historical_costs"
down_revision = "0010_add_production_movement_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.add_column(sa.Column("historical_unit_cost", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("historical_total_cost", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.drop_column("historical_total_cost")
        batch_op.drop_column("historical_unit_cost")
