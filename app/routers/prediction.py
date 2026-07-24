from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.access import Permission
from app.database import get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.prediction import DemandForecastItem, InventoryForecastItem, PredictionOverview
from app.services.prediction_service import get_demand_forecast, get_inventory_forecast, get_prediction_overview
from app.services.access_service import resolve_restaurant_access


router = APIRouter(prefix="/api/predictions", tags=["Predictions"])


@router.get("/demand", response_model=list[DemandForecastItem])
def prediction_demand(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    range: str | None = None,
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.INVENTORY_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return get_demand_forecast(db, restaurant_id=access.restaurant_id, range_value=range)


@router.get("/inventory", response_model=list[InventoryForecastItem])
def prediction_inventory(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    range: str | None = None,
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.INVENTORY_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return get_inventory_forecast(db, restaurant_id=access.restaurant_id, range_value=range)


@router.get("/overview", response_model=PredictionOverview)
def prediction_overview(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    range: str | None = None,
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.INVENTORY_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return get_prediction_overview(db, restaurant_id=access.restaurant_id, range_value=range)
