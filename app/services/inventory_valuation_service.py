from decimal import Decimal
from typing import NamedTuple

from starlette import status

from app.core.exceptions import AppError
from app.models import InventoryItem


class WeightedAverageCostTrace(NamedTuple):
    previous_stock: float
    previous_unit_cost: float | None
    resulting_unit_cost: float


def calculate_weighted_average_cost_trace(
    item: InventoryItem,
    received_quantity: float,
    purchase_unit_cost: float,
) -> WeightedAverageCostTrace:
    previous_stock = float(item.current_stock)
    if previous_stock < 0:
        raise AppError(
            "No se puede calcular coste medio con stock operativo negativo.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="weighted_average_negative_stock",
        )
    if previous_stock == 0:
        return WeightedAverageCostTrace(
            previous_stock=previous_stock,
            previous_unit_cost=item.cost,
            resulting_unit_cost=purchase_unit_cost,
        )
    if item.cost is None:
        raise AppError(
            "No se puede calcular coste medio con stock previo sin coste operativo.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="weighted_average_cost_missing",
        )

    previous_stock_decimal = Decimal(str(previous_stock))
    previous_cost_decimal = Decimal(str(item.cost))
    received_quantity_decimal = Decimal(str(received_quantity))
    purchase_unit_cost_decimal = Decimal(str(purchase_unit_cost))

    weighted_cost = (
        previous_stock_decimal * previous_cost_decimal
        + received_quantity_decimal * purchase_unit_cost_decimal
    ) / (previous_stock_decimal + received_quantity_decimal)
    return WeightedAverageCostTrace(
        previous_stock=previous_stock,
        previous_unit_cost=float(item.cost),
        resulting_unit_cost=float(weighted_cost),
    )


def calculate_weighted_average_cost(
    item: InventoryItem,
    received_quantity: float,
    purchase_unit_cost: float,
) -> float:
    return calculate_weighted_average_cost_trace(item, received_quantity, purchase_unit_cost).resulting_unit_cost
