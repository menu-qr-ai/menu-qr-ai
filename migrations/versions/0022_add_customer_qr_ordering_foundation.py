"""add customer QR ordering foundation

Revision ID: 0022_add_customer_qr_ordering_foundation
Revises: 0021_add_payment_foundation
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_add_customer_qr_ordering_foundation"
down_revision = "0021_add_payment_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("qr_codes") as batch_op:
        batch_op.add_column(
            sa.Column("table_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("access_token", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch_op.add_column(
            sa.Column("revoked_at", sa.DateTime(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_qr_codes_table_id_restaurant_tables",
            "restaurant_tables",
            ["table_id"],
            ["id"],
        )
        batch_op.create_check_constraint(
            "ck_qr_codes_status",
            "status IN ('active', 'revoked')",
        )

    op.create_index(
        "ix_qr_codes_table_id",
        "qr_codes",
        ["table_id"],
    )
    op.create_index(
        "ix_qr_codes_access_token",
        "qr_codes",
        ["access_token"],
        unique=True,
    )
    op.create_index(
        "uq_qr_codes_active_table",
        "qr_codes",
        ["table_id"],
        unique=True,
        sqlite_where=sa.text(
            "table_id IS NOT NULL AND status = 'active'"
        ),
        postgresql_where=sa.text(
            "table_id IS NOT NULL AND status = 'active'"
        ),
    )

    op.create_table(
        "customer_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer(),
            sa.ForeignKey("restaurants.id"),
            nullable=False,
        ),
        sa.Column(
            "table_id",
            sa.Integer(),
            sa.ForeignKey("restaurant_tables.id"),
            nullable=False,
        ),
        sa.Column(
            "service_session_id",
            sa.Integer(),
            sa.ForeignKey("service_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "session_token",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'expired')",
            name="ck_customer_sessions_status",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_customer_sessions_expiry",
        ),
    )
    op.create_index(
        "ix_customer_sessions_restaurant_id",
        "customer_sessions",
        ["restaurant_id"],
    )
    op.create_index(
        "ix_customer_sessions_table_id",
        "customer_sessions",
        ["table_id"],
    )
    op.create_index(
        "ix_customer_sessions_service_session_id",
        "customer_sessions",
        ["service_session_id"],
    )
    op.create_index(
        "ix_customer_sessions_session_token",
        "customer_sessions",
        ["session_token"],
        unique=True,
    )
    op.create_index(
        "ix_customer_sessions_status",
        "customer_sessions",
        ["status"],
    )
    op.create_index(
        "ix_customer_sessions_expires_at",
        "customer_sessions",
        ["expires_at"],
    )
    op.create_index(
        "uq_customer_sessions_active_service_session",
        "customer_sessions",
        ["service_session_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )

    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(
            sa.Column(
                "customer_session_id",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "reviewed_by_user_id",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("reviewed_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("rejection_reason", sa.Text(), nullable=True)
        )
        batch_op.alter_column(
            "created_by_user_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.drop_constraint(
            "ck_orders_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_orders_status",
            "status IN ('draft', 'draft_customer', "
            "'submitted_customer', 'submitted', 'cancelled', "
            "'completed')",
        )
        batch_op.create_check_constraint(
            "ck_orders_origin_actor",
            "((customer_session_id IS NULL AND "
            "created_by_user_id IS NOT NULL) OR "
            "(customer_session_id IS NOT NULL AND "
            "created_by_user_id IS NULL))",
        )
        batch_op.create_foreign_key(
            "fk_orders_customer_session_id_customer_sessions",
            "customer_sessions",
            ["customer_session_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_orders_reviewed_by_user_id_users",
            "users",
            ["reviewed_by_user_id"],
            ["id"],
        )

    op.create_index(
        "ix_orders_customer_session_id",
        "orders",
        ["customer_session_id"],
    )
    op.create_index(
        "ix_orders_reviewed_by_user_id",
        "orders",
        ["reviewed_by_user_id"],
    )
    op.create_index(
        "uq_orders_active_customer_session",
        "orders",
        ["customer_session_id"],
        unique=True,
        sqlite_where=sa.text(
            "customer_session_id IS NOT NULL AND status IN "
            "('draft_customer', 'submitted_customer')"
        ),
        postgresql_where=sa.text(
            "customer_session_id IS NOT NULL AND status IN "
            "('draft_customer', 'submitted_customer')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_orders_active_customer_session",
        table_name="orders",
    )
    op.drop_index(
        "ix_orders_reviewed_by_user_id",
        table_name="orders",
    )
    op.drop_index(
        "ix_orders_customer_session_id",
        table_name="orders",
    )
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint(
            "fk_orders_reviewed_by_user_id_users",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_orders_customer_session_id_customer_sessions",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "ck_orders_origin_actor",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_orders_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_orders_status",
            "status IN ('draft', 'submitted', 'cancelled', "
            "'completed')",
        )
        batch_op.alter_column(
            "created_by_user_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.drop_column("rejection_reason")
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("reviewed_by_user_id")
        batch_op.drop_column("customer_session_id")

    op.drop_index(
        "uq_customer_sessions_active_service_session",
        table_name="customer_sessions",
    )
    op.drop_table("customer_sessions")

    op.drop_index(
        "uq_qr_codes_active_table",
        table_name="qr_codes",
    )
    op.drop_index(
        "ix_qr_codes_access_token",
        table_name="qr_codes",
    )
    op.drop_index(
        "ix_qr_codes_table_id",
        table_name="qr_codes",
    )
    with op.batch_alter_table("qr_codes") as batch_op:
        batch_op.drop_constraint(
            "ck_qr_codes_status",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_qr_codes_table_id_restaurant_tables",
            type_="foreignkey",
        )
        batch_op.drop_column("revoked_at")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("access_token")
        batch_op.drop_column("table_id")
