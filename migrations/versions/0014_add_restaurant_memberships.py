"""add restaurant memberships

Revision ID: 0014_add_restaurant_memberships
Revises: 0013_add_inventory_movement_origin_type_index
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_add_restaurant_memberships"
down_revision = "0013_add_inventory_movement_origin_type_index"
branch_labels = None
depends_on = None

VALID_ROLES = ("owner", "manager", "waiter", "cook", "viewer")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "restaurant_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.CheckConstraint(
            "role IN ('owner', 'manager', 'waiter', 'cook', 'viewer')",
            name="ck_restaurant_memberships_role",
        ),
        sa.UniqueConstraint(
            "user_id",
            "restaurant_id",
            name="uq_restaurant_memberships_user_restaurant",
        ),
    )
    op.create_index(
        "ix_restaurant_memberships_id",
        "restaurant_memberships",
        ["id"],
    )
    op.create_index(
        "ix_restaurant_memberships_user_id",
        "restaurant_memberships",
        ["user_id"],
    )
    op.create_index(
        "ix_restaurant_memberships_restaurant_id",
        "restaurant_memberships",
        ["restaurant_id"],
    )
    op.create_index(
        "ix_restaurant_memberships_is_active",
        "restaurant_memberships",
        ["is_active"],
    )
    op.create_index(
        "ix_restaurant_memberships_created_by_user_id",
        "restaurant_memberships",
        ["created_by_user_id"],
    )

    users = sa.table(
        "users",
        sa.column("id", sa.Integer()),
        sa.column("restaurant_id", sa.Integer()),
        sa.column("role", sa.String()),
        sa.column("created_at", sa.DateTime()),
    )
    memberships = sa.table(
        "restaurant_memberships",
        sa.column("user_id", sa.Integer()),
        sa.column("restaurant_id", sa.Integer()),
        sa.column("role", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
    )
    role_expression = sa.case(
        (users.c.role.in_(VALID_ROLES), users.c.role),
        else_=sa.literal("viewer"),
    )
    statement = memberships.insert().from_select(
        ("user_id", "restaurant_id", "role", "is_active", "created_at"),
        sa.select(
            users.c.id,
            users.c.restaurant_id,
            role_expression,
            sa.true(),
            users.c.created_at,
        ).where(users.c.restaurant_id.is_not(None)),
    )
    op.get_bind().execute(statement)


def downgrade() -> None:
    op.drop_table("restaurant_memberships")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_active")
