from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from collections.abc import Iterable
from typing import Literal, TypeAlias, overload


MoneyInput: TypeAlias = Decimal | int | float | str

MONEY_PRECISION = 12
MONEY_SCALE = 2
MONEY_QUANTUM = Decimal("0.01")
MONEY_MAX = Decimal("9999999999.99")
MONEY_ROUNDING = ROUND_HALF_UP
ZERO_MONEY = Decimal("0.00")


def decimal_from_value(value: MoneyInput, *, field_name: str = "importe") -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} no es un decimal valido.")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} no es un decimal valido.") from exc
    if not amount.is_finite():
        raise ValueError(f"{field_name} debe ser finito.")
    return amount


def quantize_money(value: MoneyInput) -> Decimal:
    return decimal_from_value(value).quantize(
        MONEY_QUANTUM,
        rounding=MONEY_ROUNDING,
    )


@overload
def normalize_money(
    value: MoneyInput,
    *,
    nullable: Literal[False] = False,
    field_name: str = "importe",
) -> Decimal: ...


@overload
def normalize_money(
    value: MoneyInput | None,
    *,
    nullable: Literal[True],
    field_name: str = "importe",
) -> Decimal | None: ...


def normalize_money(
    value: MoneyInput | None,
    *,
    nullable: bool = False,
    field_name: str = "importe",
) -> Decimal | None:
    if value is None:
        if nullable:
            return None
        raise ValueError(f"{field_name} es obligatorio.")

    amount = decimal_from_value(value, field_name=field_name)
    if amount < ZERO_MONEY:
        raise ValueError(f"{field_name} no puede ser negativo.")
    if amount > MONEY_MAX:
        raise ValueError(
            f"{field_name} supera el maximo permitido de {MONEY_MAX}.",
        )

    normalized = quantize_money(amount)
    if normalized != amount:
        raise ValueError(
            f"{field_name} admite como maximo {MONEY_SCALE} decimales.",
        )
    return normalized


def money_subtotal(unit_price: MoneyInput, quantity: int) -> Decimal:
    price = normalize_money(unit_price, field_name="precio unitario")
    if quantity <= 0:
        raise ValueError("La cantidad debe ser mayor que cero.")
    return quantize_money(price * Decimal(quantity))


def sum_money(values: Iterable[MoneyInput]) -> Decimal:
    total = sum(
        (decimal_from_value(value) for value in values),
        start=ZERO_MONEY,
    )
    return quantize_money(total)


def money_to_json(value: MoneyInput | None) -> str | None:
    if value is None:
        return None
    return format(quantize_money(value), ".2f")
