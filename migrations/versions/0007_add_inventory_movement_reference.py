"""add inventory movement reference

Revision ID: 0007_add_inventory_movement_reference
Revises: 0006_harden_inventory_movement_ledger
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_add_inventory_movement_reference"
down_revision = "0006_harden_inventory_movement_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.add_column(sa.Column("reference", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.drop_column("reference")
