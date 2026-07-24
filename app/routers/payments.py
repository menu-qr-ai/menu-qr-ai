from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette import status

from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.payment import (
    PaymentBalanceRead,
    PaymentCreate,
    PaymentCreateRead,
    PaymentRead,
)
from app.services.payment_service import (
    create_payment,
    get_payment_balance,
    list_payments,
)


router = APIRouter(
    prefix="/api/dining/{restaurant_id}/settlements/{settlement_id}",
    tags=["Payments"],
)


@router.post(
    "/payments",
    response_model=PaymentCreateRead,
    status_code=status.HTTP_201_CREATED,
)
def payment_create(
    restaurant_id: int,
    settlement_id: int,
    payload: PaymentCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return create_payment(
        db,
        current_user,
        restaurant_id,
        settlement_id,
        payload,
    )


@router.get("/payments", response_model=list[PaymentRead])
def payments_index(
    restaurant_id: int,
    settlement_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return list_payments(
        db,
        current_user,
        restaurant_id,
        settlement_id,
    )


@router.get("/balance", response_model=PaymentBalanceRead)
def payment_balance(
    restaurant_id: int,
    settlement_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return get_payment_balance(
        db,
        current_user,
        restaurant_id,
        settlement_id,
    )
