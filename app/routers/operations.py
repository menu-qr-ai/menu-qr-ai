from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.access import Permission
from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.operational_transaction import SaleTransactionCreate, SaleTransactionResult
from app.services.operational_transaction_service import process_sale_transaction
from app.services.access_service import authorize_restaurant


router = APIRouter(prefix="/api/operations", tags=["Operations"])


@router.post("/sales", response_model=SaleTransactionResult)
def process_sale(
    payload: SaleTransactionCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, payload.restaurant_id, Permission.OPERATIONS_WRITE)
    return process_sale_transaction(db, payload)
