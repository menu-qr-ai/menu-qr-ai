"""harden technical recipes

Revision ID: 0005_harden_technical_recipes
Revises: 0004_add_inventory_domain
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_harden_technical_recipes"
down_revision = "0004_add_inventory_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM dish_ingredients "
            "WHERE id NOT IN ("
            "SELECT MIN(id) FROM dish_ingredients "
            "GROUP BY restaurant_id, dish_id, inventory_item_id"
            ")"
        )
    )

    with op.batch_alter_table("dish_ingredients") as batch_op:
        batch_op.create_unique_constraint(
            "uq_dish_ingredients_recipe_item",
            ["restaurant_id", "dish_id", "inventory_item_id"],
        )
        batch_op.create_check_constraint(
            "ck_dish_ingredients_quantity_positive",
            "quantity > 0",
        )
        batch_op.create_check_constraint(
            "ck_dish_ingredients_unit_allowed",
            "unit IN ('g', 'kg', 'ml', 'l', 'unit')",
        )


def downgrade() -> None:
    with op.batch_alter_table("dish_ingredients") as batch_op:
        batch_op.drop_constraint("ck_dish_ingredients_unit_allowed", type_="check")
        batch_op.drop_constraint("ck_dish_ingredients_quantity_positive", type_="check")
        batch_op.drop_constraint("uq_dish_ingredients_recipe_item", type_="unique")
