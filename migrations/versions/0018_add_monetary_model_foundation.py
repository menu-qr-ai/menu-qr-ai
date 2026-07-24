"""add monetary model foundation

Revision ID: 0018_add_monetary_model_foundation
Revises: 0017_add_kitchen_ticket_foundation
Create Date: 2026-07-23
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from alembic import op
import sqlalchemy as sa


revision = "0018_add_monetary_model_foundation"
down_revision = "0017_add_kitchen_ticket_foundation"
branch_labels = None
depends_on = None

MONEY_TYPE = sa.Numeric(precision=12, scale=2)
MONEY_QUANTUM = Decimal("0.01")
MONEY_MAX = Decimal("9999999999.99")


def _validate_existing_values() -> None:
    bind = op.get_bind()
    fields = (
        ("dishes", "price", True),
        ("order_lines", "unit_price", False),
    )
    for table_name, column_name, nullable in fields:
        rows = bind.execute(
            sa.text(
                f"SELECT id, {column_name} AS monetary_value "
                f"FROM {table_name} ORDER BY id"
            )
        ).mappings()
        for row in rows:
            value = row["monetary_value"]
            if value is None:
                if nullable:
                    continue
                _blocked(table_name, column_name, row["id"], "NULL no permitido")
            try:
                amount = Decimal(str(value))
            except (InvalidOperation, ValueError):
                _blocked(table_name, column_name, row["id"], "valor no decimal")
            if not amount.is_finite():
                _blocked(table_name, column_name, row["id"], "valor no finito")
            try:
                normalized = amount.quantize(
                    MONEY_QUANTUM,
                    rounding=ROUND_HALF_UP,
                )
            except InvalidOperation:
                _blocked(table_name, column_name, row["id"], "fuera de rango")
            if amount < 0:
                _blocked(table_name, column_name, row["id"], "valor negativo")
            if amount > MONEY_MAX:
                _blocked(table_name, column_name, row["id"], "fuera de rango")
            if normalized != amount:
                _blocked(
                    table_name,
                    column_name,
                    row["id"],
                    "mas de dos decimales significativos",
                )


def _blocked(
    table_name: str,
    column_name: str,
    row_id: int,
    reason: str,
) -> None:
    raise RuntimeError(
        "Monetary migration blocked: "
        f"{table_name}.{column_name} id={row_id}: {reason}.",
    )


def _upgrade_column_types() -> None:
    if op.get_context().dialect.name == "sqlite":
        with op.batch_alter_table("dishes") as batch_op:
            batch_op.alter_column(
                "price",
                existing_type=sa.Float(),
                type_=MONEY_TYPE,
                existing_nullable=True,
            )
            batch_op.create_check_constraint(
                "ck_dishes_price_range",
                "price IS NULL OR "
                "(price >= 0 AND price <= 9999999999.99)",
            )
        with op.batch_alter_table("order_lines") as batch_op:
            batch_op.alter_column(
                "unit_price",
                existing_type=sa.Float(),
                type_=MONEY_TYPE,
                existing_nullable=False,
            )
            batch_op.create_check_constraint(
                "ck_order_lines_unit_price_max",
                "unit_price <= 9999999999.99",
            )
        return

    op.alter_column(
        "dishes",
        "price",
        existing_type=sa.Float(),
        type_=MONEY_TYPE,
        existing_nullable=True,
        postgresql_using="ROUND(price::numeric, 2)",
    )
    op.create_check_constraint(
        "ck_dishes_price_range",
        "dishes",
        "price IS NULL OR (price >= 0 AND price <= 9999999999.99)",
    )
    op.alter_column(
        "order_lines",
        "unit_price",
        existing_type=sa.Float(),
        type_=MONEY_TYPE,
        existing_nullable=False,
        postgresql_using="ROUND(unit_price::numeric, 2)",
    )
    op.create_check_constraint(
        "ck_order_lines_unit_price_max",
        "order_lines",
        "unit_price <= 9999999999.99",
    )


def upgrade() -> None:
    _validate_existing_values()
    _upgrade_column_types()


def downgrade() -> None:
    if op.get_context().dialect.name == "sqlite":
        with op.batch_alter_table("order_lines") as batch_op:
            batch_op.drop_constraint(
                "ck_order_lines_unit_price_max",
                type_="check",
            )
            batch_op.alter_column(
                "unit_price",
                existing_type=MONEY_TYPE,
                type_=sa.Float(),
                existing_nullable=False,
            )
        with op.batch_alter_table("dishes") as batch_op:
            batch_op.drop_constraint(
                "ck_dishes_price_range",
                type_="check",
            )
            batch_op.alter_column(
                "price",
                existing_type=MONEY_TYPE,
                type_=sa.Float(),
                existing_nullable=True,
            )
        return

    op.drop_constraint(
        "ck_order_lines_unit_price_max",
        "order_lines",
        type_="check",
    )
    op.alter_column(
        "order_lines",
        "unit_price",
        existing_type=MONEY_TYPE,
        type_=sa.Float(),
        existing_nullable=False,
        postgresql_using="unit_price::double precision",
    )
    op.drop_constraint(
        "ck_dishes_price_range",
        "dishes",
        type_="check",
    )
    op.alter_column(
        "dishes",
        "price",
        existing_type=MONEY_TYPE,
        type_=sa.Float(),
        existing_nullable=True,
        postgresql_using="price::double precision",
    )
