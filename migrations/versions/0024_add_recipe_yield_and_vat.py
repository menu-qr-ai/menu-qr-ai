"""add recipe yield and restaurant VAT

Revision ID: 0024_add_recipe_yield_and_vat
Revises: 0023_add_menu_management
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0024_add_recipe_yield_and_vat"
down_revision = "0023_add_menu_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Usable share of the ingredient after cleaning/trimming. 100 keeps
    # existing recipes behaving exactly as before.
    with op.batch_alter_table("dish_ingredients") as batch_op:
        batch_op.add_column(
            sa.Column("yield_percentage", sa.Float(), nullable=False, server_default="100")
        )
        batch_op.create_check_constraint(
            "ck_dish_ingredients_yield_range",
            "yield_percentage > 0 AND yield_percentage <= 100",
        )

    # Menu prices include VAT; food cost must be measured without it.
    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.add_column(
            sa.Column("vat_percentage", sa.Numeric(5, 2), nullable=False, server_default="10")
        )


def downgrade() -> None:
    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.drop_column("vat_percentage")

    with op.batch_alter_table("dish_ingredients") as batch_op:
        batch_op.drop_constraint("ck_dish_ingredients_yield_range", type_="check")
        batch_op.drop_column("yield_percentage")
