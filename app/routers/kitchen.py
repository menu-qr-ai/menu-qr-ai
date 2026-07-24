from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.kitchen import KitchenStatus
from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.kitchen import KitchenTicketRead
from app.services.kitchen_ticket_service import (
    cancel_kitchen_ticket,
    cancel_kitchen_ticket_line,
    get_kitchen_ticket,
    get_order_kitchen_ticket,
    list_kitchen_tickets,
    ready_kitchen_ticket,
    ready_kitchen_ticket_line,
    serve_kitchen_ticket,
    start_kitchen_ticket,
    start_kitchen_ticket_line,
)


router = APIRouter(prefix="/api/kitchen/{restaurant_id}", tags=["Kitchen"])


@router.get("/tickets", response_model=list[KitchenTicketRead])
def kitchen_ticket_index(
    restaurant_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    ticket_status: KitchenStatus | None = Query(default=None, alias="status"),
    active_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return list_kitchen_tickets(
        db,
        current_user,
        restaurant_id,
        ticket_status=ticket_status,
        active_only=active_only,
    )


@router.get("/tickets/{ticket_id}", response_model=KitchenTicketRead)
def kitchen_ticket_detail(
    restaurant_id: int,
    ticket_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return get_kitchen_ticket(db, current_user, restaurant_id, ticket_id)


@router.get("/orders/{order_id}/ticket", response_model=KitchenTicketRead)
def order_kitchen_ticket_detail(
    restaurant_id: int,
    order_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return get_order_kitchen_ticket(db, current_user, restaurant_id, order_id)


@router.post("/tickets/{ticket_id}/start", response_model=KitchenTicketRead)
def kitchen_ticket_start(
    restaurant_id: int,
    ticket_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return start_kitchen_ticket(db, current_user, restaurant_id, ticket_id)


@router.post("/tickets/{ticket_id}/ready", response_model=KitchenTicketRead)
def kitchen_ticket_ready(
    restaurant_id: int,
    ticket_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return ready_kitchen_ticket(db, current_user, restaurant_id, ticket_id)


@router.post("/tickets/{ticket_id}/serve", response_model=KitchenTicketRead)
def kitchen_ticket_serve(
    restaurant_id: int,
    ticket_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return serve_kitchen_ticket(db, current_user, restaurant_id, ticket_id)


@router.post("/tickets/{ticket_id}/cancel", response_model=KitchenTicketRead)
def kitchen_ticket_cancel(
    restaurant_id: int,
    ticket_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return cancel_kitchen_ticket(db, current_user, restaurant_id, ticket_id)


@router.post(
    "/tickets/{ticket_id}/lines/{line_id}/start",
    response_model=KitchenTicketRead,
)
def kitchen_ticket_line_start(
    restaurant_id: int,
    ticket_id: int,
    line_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return start_kitchen_ticket_line(
        db,
        current_user,
        restaurant_id,
        ticket_id,
        line_id,
    )


@router.post(
    "/tickets/{ticket_id}/lines/{line_id}/ready",
    response_model=KitchenTicketRead,
)
def kitchen_ticket_line_ready(
    restaurant_id: int,
    ticket_id: int,
    line_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return ready_kitchen_ticket_line(
        db,
        current_user,
        restaurant_id,
        ticket_id,
        line_id,
    )


@router.post(
    "/tickets/{ticket_id}/lines/{line_id}/cancel",
    response_model=KitchenTicketRead,
)
def kitchen_ticket_line_cancel(
    restaurant_id: int,
    ticket_id: int,
    line_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return cancel_kitchen_ticket_line(
        db,
        current_user,
        restaurant_id,
        ticket_id,
        line_id,
    )
