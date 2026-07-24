import hashlib
import secrets
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.exceptions import AppError
from app.core.money import money_to_json, normalize_money
from app.core.orders import CUSTOMER_PENDING_ORDER_STATUSES, OrderStatus
from app.models import (
    Category,
    Dish,
    DishIngredient,
    Order,
    OrderLine,
)
from app.schemas.customer import (
    CustomerCategoryRead,
    CustomerDishRead,
    CustomerOrderCreate,
    CustomerOrderLineCreate,
    CustomerOrderLineRead,
    CustomerOrderLineUpdate,
    CustomerOrderRead,
    CustomerRestaurantRead,
    CustomerSessionStateRead,
)
from app.services.customer_session_service import (
    require_customer_session,
    touch_customer_session,
)


def get_customer_session_state(
    db: Session,
    session_token: str,
) -> CustomerSessionStateRead:
    customer_session = require_customer_session(db, session_token)
    restaurant_id = customer_session.restaurant_id
    categories = list(
        db.scalars(
            select(Category)
            .where(Category.restaurant_id == restaurant_id)
            .order_by(Category.name, Category.id)
        ).all()
    )
    dishes = _load_customer_dishes(db, restaurant_id)
    orders = _load_customer_orders(db, customer_session.id)
    restaurant = customer_session.restaurant
    return CustomerSessionStateRead(
        status=customer_session.status,
        table_code=customer_session.table.code,
        expires_at=customer_session.expires_at,
        restaurant=CustomerRestaurantRead(
            name=restaurant.name,
            currency=restaurant.currency or "EUR",
            logo_url=restaurant.logo_url,
            primary_color=restaurant.primary_color,
            accent_color=restaurant.accent_color,
        ),
        categories=[
            CustomerCategoryRead(id=item.id, name=item.name)
            for item in categories
        ],
        dishes=[
            _customer_dish_schema(item)
            for item in dishes
        ],
        orders=[
            _customer_order_schema(order)
            for order in orders
        ],
    )


def create_customer_order(
    db: Session,
    session_token: str,
    payload: CustomerOrderCreate,
) -> CustomerSessionStateRead:
    customer_session = require_customer_session(
        db,
        session_token,
        lock=True,
    )
    existing = _active_customer_order(
        db,
        customer_session.id,
    )
    if existing is not None:
        if existing.status == OrderStatus.DRAFT_CUSTOMER.value:
            return get_customer_session_state(db, session_token)
        raise AppError(
            "El pedido anterior sigue pendiente de revision.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_pending_review",
        )

    now = datetime.utcnow()
    order = Order(
        restaurant_id=customer_session.restaurant_id,
        service_session_id=customer_session.service_session_id,
        customer_session_id=customer_session.id,
        status=OrderStatus.DRAFT_CUSTOMER.value,
        note=payload.note,
        idempotency_key=_idempotency_key(
            "customer-order",
            customer_session.id,
            payload.idempotency_key or secrets.token_urlsafe(18),
        ),
        created_by_user_id=None,
        created_at=now,
        updated_at=now,
    )
    touch_customer_session(customer_session, now)
    db.add(order)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent = _active_customer_order(
            db,
            customer_session.id,
        )
        if (
            concurrent is not None
            and concurrent.status
            == OrderStatus.DRAFT_CUSTOMER.value
        ):
            return get_customer_session_state(db, session_token)
        raise AppError(
            "No se pudo crear el borrador del cliente.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_conflict",
        ) from exc
    return get_customer_session_state(db, session_token)


def add_customer_order_line(
    db: Session,
    session_token: str,
    payload: CustomerOrderLineCreate,
) -> CustomerSessionStateRead:
    customer_session, order = _editable_customer_order(
        db,
        session_token,
    )
    if payload.idempotency_key:
        key = _idempotency_key(
            "customer-line",
            order.id,
            payload.idempotency_key,
        )
        if _line_by_idempotency_key(db, order.id, key) is not None:
            return get_customer_session_state(db, session_token)
    else:
        key = None

    dish = _require_customer_dish(
        db,
        customer_session.restaurant_id,
        payload.dish_id,
    )
    quantities = _order_dish_quantities(order)
    quantities[dish.id] += payload.quantity
    _validate_dish_quantities(
        db,
        customer_session.restaurant_id,
        quantities,
    )
    now = datetime.utcnow()
    db.add(
        OrderLine(
            restaurant_id=customer_session.restaurant_id,
            order_id=order.id,
            dish_id=dish.id,
            dish_name=dish.name,
            quantity=payload.quantity,
            unit_price=normalize_money(
                dish.price,
                field_name="El precio del plato",
            ),
            note=payload.note,
            idempotency_key=key,
            created_at=now,
            updated_at=now,
        )
    )
    touch_customer_session(customer_session, now)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if (
            key is not None
            and _line_by_idempotency_key(
                db,
                order.id,
                key,
            )
            is not None
        ):
            return get_customer_session_state(db, session_token)
        raise AppError(
            "No se pudo anadir el plato.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_line_conflict",
        ) from exc
    return get_customer_session_state(db, session_token)


def update_customer_order_line(
    db: Session,
    session_token: str,
    line_id: int,
    payload: CustomerOrderLineUpdate,
) -> CustomerSessionStateRead:
    customer_session, order = _editable_customer_order(
        db,
        session_token,
    )
    line = _require_customer_order_line(
        db,
        customer_session.restaurant_id,
        order.id,
        line_id,
    )
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return get_customer_session_state(db, session_token)
    next_quantity = changes.get("quantity", line.quantity)
    quantities = _order_dish_quantities(
        order,
        replace_line=(line.id, next_quantity),
    )
    _validate_dish_quantities(
        db,
        customer_session.restaurant_id,
        quantities,
    )
    for field, value in changes.items():
        setattr(line, field, value)
    now = datetime.utcnow()
    line.updated_at = now
    touch_customer_session(customer_session, now)
    db.commit()
    return get_customer_session_state(db, session_token)


def delete_customer_order_line(
    db: Session,
    session_token: str,
    line_id: int,
) -> CustomerSessionStateRead:
    customer_session, order = _editable_customer_order(
        db,
        session_token,
    )
    line = _require_customer_order_line(
        db,
        customer_session.restaurant_id,
        order.id,
        line_id,
    )
    touch_customer_session(customer_session)
    db.delete(line)
    db.commit()
    return get_customer_session_state(db, session_token)


def submit_customer_order(
    db: Session,
    session_token: str,
) -> CustomerSessionStateRead:
    customer_session = require_customer_session(
        db,
        session_token,
        lock=True,
    )
    order = _active_customer_order(
        db,
        customer_session.id,
    )
    if (
        order is not None
        and order.status
        == OrderStatus.SUBMITTED_CUSTOMER.value
    ):
        return get_customer_session_state(db, session_token)
    if (
        order is None
        or order.status != OrderStatus.DRAFT_CUSTOMER.value
    ):
        raise AppError(
            "No existe un borrador de cliente editable.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_not_editable",
        )
    if not order.lines:
        raise AppError(
            "No se puede enviar un pedido sin platos.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_empty",
        )
    validate_customer_order_availability(db, order)
    now = datetime.utcnow()
    order.status = OrderStatus.SUBMITTED_CUSTOMER.value
    order.submitted_at = now
    order.updated_at = now
    touch_customer_session(customer_session, now)
    db.commit()
    return get_customer_session_state(db, session_token)


def validate_customer_order_availability(
    db: Session,
    order: Order,
) -> None:
    _validate_dish_quantities(
        db,
        order.restaurant_id,
        _order_dish_quantities(order),
    )


def _load_customer_dishes(
    db: Session,
    restaurant_id: int,
) -> list[Dish]:
    return list(
        db.scalars(
            select(Dish)
            .options(
                selectinload(Dish.dish_ingredients).selectinload(
                    DishIngredient.inventory_item
                )
            )
            .where(Dish.restaurant_id == restaurant_id)
            .order_by(Dish.category_id, Dish.name, Dish.id)
        ).all()
    )


def _customer_dish_schema(dish: Dish) -> CustomerDishRead:
    available = _dish_is_available(dish)
    return CustomerDishRead(
        id=dish.id,
        category_id=dish.category_id,
        name=dish.name,
        description=dish.description or "",
        price=money_to_json(dish.price),
        ingredients=dish.ingredients or "",
        allergens=dish.allergens or "",
        image=dish.image or "",
        is_available=available,
        availability_label=(
            "Disponible" if available else "No disponible ahora"
        ),
    )


def _dish_is_available(
    dish: Dish,
    quantity: int = 1,
) -> bool:
    if dish.price is None or not dish.dish_ingredients:
        return False
    return all(
        link.inventory_item is not None
        and link.inventory_item.is_active
        and link.inventory_item.restaurant_id == dish.restaurant_id
        and link.restaurant_id == dish.restaurant_id
        and link.inventory_item.current_stock
        >= link.quantity * quantity
        for link in dish.dish_ingredients
    )


def _validate_dish_quantities(
    db: Session,
    restaurant_id: int,
    quantities: dict[int, int],
) -> None:
    if not quantities:
        return
    dishes = _load_customer_dishes(db, restaurant_id)
    dishes_by_id = {
        dish.id: dish
        for dish in dishes
        if dish.id in quantities
    }
    if set(dishes_by_id) != set(quantities):
        _raise_dish_unavailable()

    ingredient_requirements: dict[int, float] = defaultdict(float)
    ingredients = {}
    for dish_id, quantity in quantities.items():
        dish = dishes_by_id[dish_id]
        if dish.price is None or not dish.dish_ingredients:
            _raise_dish_unavailable()
        for link in dish.dish_ingredients:
            item = link.inventory_item
            if (
                item is None
                or not item.is_active
                or item.restaurant_id != restaurant_id
                or link.restaurant_id != restaurant_id
            ):
                _raise_dish_unavailable()
            ingredient_requirements[item.id] += (
                link.quantity * quantity
            )
            ingredients[item.id] = item
    if any(
        ingredients[item_id].current_stock < required
        for item_id, required in ingredient_requirements.items()
    ):
        _raise_dish_unavailable()


def _raise_dish_unavailable() -> None:
    raise AppError(
        "Uno de los platos ya no esta disponible.",
        status_code=status.HTTP_409_CONFLICT,
        code="customer_dish_unavailable",
    )


def _editable_customer_order(
    db: Session,
    session_token: str,
) -> tuple:
    customer_session = require_customer_session(
        db,
        session_token,
        lock=True,
    )
    order = _active_customer_order(
        db,
        customer_session.id,
    )
    if (
        order is None
        or order.status != OrderStatus.DRAFT_CUSTOMER.value
    ):
        raise AppError(
            "El pedido de cliente ya no se puede modificar.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_not_editable",
        )
    return customer_session, order


def _active_customer_order(
    db: Session,
    customer_session_id: int,
) -> Order | None:
    return db.scalar(
        select(Order)
        .options(selectinload(Order.lines))
        .where(
            Order.customer_session_id == customer_session_id,
            Order.status.in_(CUSTOMER_PENDING_ORDER_STATUSES),
        )
    )


def _load_customer_orders(
    db: Session,
    customer_session_id: int,
) -> list[Order]:
    return list(
        db.scalars(
            select(Order)
            .options(selectinload(Order.lines))
            .where(Order.customer_session_id == customer_session_id)
            .order_by(Order.created_at, Order.id)
        ).all()
    )


def _require_customer_dish(
    db: Session,
    restaurant_id: int,
    dish_id: int,
) -> Dish:
    dish = db.scalar(
        select(Dish).where(
            Dish.id == dish_id,
            Dish.restaurant_id == restaurant_id,
        )
    )
    if dish is None:
        raise AppError(
            "Plato no disponible.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="customer_dish_not_found",
        )
    return dish


def _require_customer_order_line(
    db: Session,
    restaurant_id: int,
    order_id: int,
    line_id: int,
) -> OrderLine:
    line = db.scalar(
        select(OrderLine).where(
            OrderLine.id == line_id,
            OrderLine.order_id == order_id,
            OrderLine.restaurant_id == restaurant_id,
        )
    )
    if line is None:
        raise AppError(
            "Linea de pedido no encontrada.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="customer_order_line_not_found",
        )
    return line


def _order_dish_quantities(
    order: Order,
    *,
    replace_line: tuple[int, int] | None = None,
) -> dict[int, int]:
    quantities: dict[int, int] = defaultdict(int)
    for line in order.lines:
        quantity = (
            replace_line[1]
            if replace_line is not None
            and line.id == replace_line[0]
            else line.quantity
        )
        quantities[line.dish_id] += quantity
    return quantities


def _line_by_idempotency_key(
    db: Session,
    order_id: int,
    key: str,
) -> OrderLine | None:
    return db.scalar(
        select(OrderLine).where(
            OrderLine.order_id == order_id,
            OrderLine.idempotency_key == key,
        )
    )


def _idempotency_key(
    namespace: str,
    parent_id: int,
    client_key: str,
) -> str:
    raw = f"{namespace}:{parent_id}:{client_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _customer_order_schema(order: Order) -> CustomerOrderRead:
    return CustomerOrderRead(
        status=order.status,
        note=order.note,
        lines=[
            CustomerOrderLineRead(
                id=line.id,
                dish_id=line.dish_id,
                dish_name=line.dish_name,
                quantity=line.quantity,
                unit_price=money_to_json(line.unit_price),
                note=line.note,
                subtotal=money_to_json(line.subtotal),
            )
            for line in order.lines
        ],
        total_amount=money_to_json(order.total_amount),
        total_units=order.total_units,
        reviewed_at=order.reviewed_at,
        rejection_reason=order.rejection_reason,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )
