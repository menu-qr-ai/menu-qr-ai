"""add inventory movement wac trace

Revision ID: 0012_add_inventory_movement_wac_trace
Revises: 0011_add_inventory_movement_historical_costs
Create Date: 2026-07-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012_add_inventory_movement_wac_trace"
down_revision = "0011_add_inventory_movement_historical_costs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.add_column(sa.Column("wac_previous_stock", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("wac_previous_unit_cost", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("wac_resulting_unit_cost", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.drop_column("wac_resulting_unit_cost")
        batch_op.drop_column("wac_previous_unit_cost")
        batch_op.drop_column("wac_previous_stock")
