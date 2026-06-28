"""add saas tables

Revision ID: 0001_add_saas_tables
Revises:
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_add_saas_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False, server_default="owner"),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_restaurant_id", "users", ["restaurant_id"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("plan", sa.String(), nullable=False, server_default="free"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("provider_customer_id", sa.String(), nullable=True),
        sa.Column("provider_subscription_id", sa.String(), nullable=True),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_subscriptions_restaurant_id", "subscriptions", ["restaurant_id"])
    op.create_index("ix_subscriptions_provider_customer_id", "subscriptions", ["provider_customer_id"])
    op.create_index("ix_subscriptions_provider_subscription_id", "subscriptions", ["provider_subscription_id"])

    op.create_table(
        "translations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dish_id", sa.Integer(), sa.ForeignKey("dishes.id"), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ingredients", sa.Text(), nullable=True),
        sa.Column("allergens", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False, server_default="openai"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_translations_dish_id", "translations", ["dish_id"])
    op.create_index("ix_translations_language", "translations", ["language"])

    op.create_table(
        "qr_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("target_url", sa.String(), nullable=False),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_qr_codes_restaurant_id", "qr_codes", ["restaurant_id"])

    op.create_table(
        "usage_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=True),
        sa.Column("feature", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="success"),
        sa.Column("units", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_usage_logs_restaurant_id", "usage_logs", ["restaurant_id"])
    op.create_index("ix_usage_logs_feature", "usage_logs", ["feature"])

    op.create_table(
        "image_generations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dish_id", sa.Integer(), sa.ForeignKey("dishes.id"), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False, server_default="openai"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_image_generations_dish_id", "image_generations", ["dish_id"])


def downgrade() -> None:
    op.drop_table("image_generations")
    op.drop_table("usage_logs")
    op.drop_table("qr_codes")
    op.drop_table("translations")
    op.drop_table("subscriptions")
    op.drop_table("users")
