"""add inventory domain

Revision ID: 0004_add_inventory_domain
Revises: 0003_extend_restaurants_for_multitenancy
Create Date: 2026-06-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_add_inventory_domain"
down_revision = "0003_extend_restaurants_for_multitenancy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False, server_default="unit"),
        sa.Column("current_stock", sa.Float(), nullable=False, server_default="0"),
        sa.Column("minimum_stock", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ideal_stock", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("supplier", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_items_id", "inventory_items", ["id"])
    op.create_index("ix_inventory_items_name", "inventory_items", ["name"])
    op.create_index("ix_inventory_items_restaurant_id", "inventory_items", ["restaurant_id"])

    op.create_table(
        "dish_ingredients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("dish_id", sa.Integer(), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"]),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dish_ingredients_id", "dish_ingredients", ["id"])
    op.create_index("ix_dish_ingredients_dish_id", "dish_ingredients", ["dish_id"])
    op.create_index("ix_dish_ingredients_inventory_item_id", "dish_ingredients", ["inventory_item_id"])
    op.create_index("ix_dish_ingredients_restaurant_id", "dish_ingredients", ["restaurant_id"])

    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), nullable=False),
        sa.Column("movement_type", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_movements_id", "inventory_movements", ["id"])
    op.create_index("ix_inventory_movements_created_at", "inventory_movements", ["created_at"])
    op.create_index("ix_inventory_movements_inventory_item_id", "inventory_movements", ["inventory_item_id"])
    op.create_index("ix_inventory_movements_movement_type", "inventory_movements", ["movement_type"])
    op.create_index("ix_inventory_movements_restaurant_id", "inventory_movements", ["restaurant_id"])

    op.create_table(
        "inventory_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), nullable=True),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_alerts_id", "inventory_alerts", ["id"])
    op.create_index("ix_inventory_alerts_created_at", "inventory_alerts", ["created_at"])
    op.create_index("ix_inventory_alerts_inventory_item_id", "inventory_alerts", ["inventory_item_id"])
    op.create_index("ix_inventory_alerts_restaurant_id", "inventory_alerts", ["restaurant_id"])
    op.create_index("ix_inventory_alerts_severity", "inventory_alerts", ["severity"])

    op.create_table(
        "inventory_insights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), nullable=True),
        sa.Column("dish_id", sa.Integer(), nullable=True),
        sa.Column("insight_type", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dish_id"], ["dishes.id"]),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_insights_id", "inventory_insights", ["id"])
    op.create_index("ix_inventory_insights_created_at", "inventory_insights", ["created_at"])
    op.create_index("ix_inventory_insights_dish_id", "inventory_insights", ["dish_id"])
    op.create_index("ix_inventory_insights_insight_type", "inventory_insights", ["insight_type"])
    op.create_index("ix_inventory_insights_inventory_item_id", "inventory_insights", ["inventory_item_id"])
    op.create_index("ix_inventory_insights_restaurant_id", "inventory_insights", ["restaurant_id"])


def downgrade() -> None:
    op.drop_index("ix_inventory_insights_restaurant_id", table_name="inventory_insights")
    op.drop_index("ix_inventory_insights_inventory_item_id", table_name="inventory_insights")
    op.drop_index("ix_inventory_insights_insight_type", table_name="inventory_insights")
    op.drop_index("ix_inventory_insights_dish_id", table_name="inventory_insights")
    op.drop_index("ix_inventory_insights_created_at", table_name="inventory_insights")
    op.drop_index("ix_inventory_insights_id", table_name="inventory_insights")
    op.drop_table("inventory_insights")
    op.drop_index("ix_inventory_alerts_severity", table_name="inventory_alerts")
    op.drop_index("ix_inventory_alerts_restaurant_id", table_name="inventory_alerts")
    op.drop_index("ix_inventory_alerts_inventory_item_id", table_name="inventory_alerts")
    op.drop_index("ix_inventory_alerts_created_at", table_name="inventory_alerts")
    op.drop_index("ix_inventory_alerts_id", table_name="inventory_alerts")
    op.drop_table("inventory_alerts")
    op.drop_index("ix_inventory_movements_restaurant_id", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_movement_type", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_inventory_item_id", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_created_at", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_id", table_name="inventory_movements")
    op.drop_table("inventory_movements")
    op.drop_index("ix_dish_ingredients_restaurant_id", table_name="dish_ingredients")
    op.drop_index("ix_dish_ingredients_inventory_item_id", table_name="dish_ingredients")
    op.drop_index("ix_dish_ingredients_dish_id", table_name="dish_ingredients")
    op.drop_index("ix_dish_ingredients_id", table_name="dish_ingredients")
    op.drop_table("dish_ingredients")
    op.drop_index("ix_inventory_items_restaurant_id", table_name="inventory_items")
    op.drop_index("ix_inventory_items_name", table_name="inventory_items")
    op.drop_index("ix_inventory_items_id", table_name="inventory_items")
    op.drop_table("inventory_items")
