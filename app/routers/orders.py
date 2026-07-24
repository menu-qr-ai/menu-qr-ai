from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from starlette import status

from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.customer import CustomerOrderReview
from app.schemas.order import OrderCreate, OrderLineCreate, OrderLineUpdate, OrderRead
from app.schemas.fulfillment import OrderFulfillmentRead
from app.services.order_fulfillment_service import (
    fulfill_order,
    get_order_fulfillment,
)
from app.services.order_service import (
    add_order_line,
    approve_customer_order,
    cancel_order,
    complete_order,
    create_order,
    delete_order_line,
    get_order,
    list_session_orders,
    reject_customer_order,
    submit_order,
    update_order_line,
)


router = APIRouter(prefix="/api/orders/{restaurant_id}", tags=["Orders"])


@router.get("/sessions/{service_session_id}", response_model=list[OrderRead])
def session_orders_index(
    restaurant_id: int,
    service_session_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return list_session_orders(db, current_user, restaurant_id, service_session_id)


@router.post(
    "/sessions/{service_session_id}",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
)
def order_create(
    restaurant_id: int,
    service_session_id: int,
    payload: OrderCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return create_order(db, current_user, restaurant_id, service_session_id, payload)


@router.get("/{order_id}", response_model=OrderRead)
def order_detail(
    restaurant_id: int,
    order_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return get_order(db, current_user, restaurant_id, order_id)


@router.post("/{order_id}/lines", response_model=OrderRead)
def order_line_create(
    restaurant_id: int,
    order_id: int,
    payload: OrderLineCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return add_order_line(db, current_user, restaurant_id, order_id, payload)


@router.patch("/{order_id}/lines/{line_id}", response_model=OrderRead)
def order_line_update(
    restaurant_id: int,
    order_id: int,
    line_id: int,
    payload: OrderLineUpdate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return update_order_line(db, current_user, restaurant_id, order_id, line_id, payload)


@router.delete(
    "/{order_id}/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def order_line_delete(
    restaurant_id: int,
    order_id: int,
    line_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    delete_order_line(db, current_user, restaurant_id, order_id, line_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{order_id}/submit", response_model=OrderRead)
def order_submit(
    restaurant_id: int,
    order_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return submit_order(db, current_user, restaurant_id, order_id)


@router.post(
    "/{order_id}/customer-approval",
    response_model=OrderRead,
)
def customer_order_approve(
    restaurant_id: int,
    order_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return approve_customer_order(
        db,
        current_user,
        restaurant_id,
        order_id,
    )


@router.post(
    "/{order_id}/customer-rejection",
    response_model=OrderRead,
)
def customer_order_reject(
    restaurant_id: int,
    order_id: int,
    payload: CustomerOrderReview,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return reject_customer_order(
        db,
        current_user,
        restaurant_id,
        order_id,
        reason=payload.reason,
    )


@router.post("/{order_id}/cancel", response_model=OrderRead)
def order_cancel(
    restaurant_id: int,
    order_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return cancel_order(db, current_user, restaurant_id, order_id)


@router.post("/{order_id}/complete", response_model=OrderRead)
def order_complete(
    restaurant_id: int,
    order_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return complete_order(db, current_user, restaurant_id, order_id)


@router.post(
    "/{order_id}/fulfill",
    response_model=OrderFulfillmentRead,
)
def order_fulfill(
    restaurant_id: int,
    order_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return fulfill_order(db, current_user, restaurant_id, order_id)


@router.get(
    "/{order_id}/fulfillment",
    response_model=OrderFulfillmentRead,
)
def order_fulfillment_detail(
    restaurant_id: int,
    order_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return get_order_fulfillment(
        db,
        current_user,
        restaurant_id,
        order_id,
    )
