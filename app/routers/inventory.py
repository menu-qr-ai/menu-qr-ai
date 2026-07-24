from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi import Query
from sqlalchemy.orm import Session

from app.core.access import Permission
from app.database import get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.inventory import (
    DishIngredientCreate,
    DishIngredientRead,
    InventoryAlertRead,
    InventoryAdjustmentCreate,
    InventoryAdjustmentResult,
    InventoryInsightRead,
    InventoryItemCreate,
    InventoryItemRead,
    InventoryItemUpdate,
    LedgerAuditResponse,
    InventoryMovementCreate,
    InventoryMovementRead,
    InventoryOverview,
    InventoryProductionCreate,
    InventoryProductionRead,
    InventoryReconciliationResponse,
    InventoryWasteLossCreate,
    InventoryWasteLossRead,
    PurchaseIntakeCreate,
    PurchaseIntakeRead,
    PurchaseIntakeResult,
)
from app.schemas.planning import InventoryPlanningItem, InventoryPlanningResponse
from app.services.inventory_service import (
    create_dish_ingredient,
    create_inventory_item,
    create_inventory_movement,
    get_inventory_alerts,
    get_inventory_insights,
    get_inventory_overview,
    list_inventory_items,
    require_inventory_item,
    update_inventory_item,
)
from app.services.inventory_adjustment_service import (
    get_inventory_reconciliation,
    record_inventory_adjustment,
)
from app.services.inventory_ledger_audit_service import MAX_LEDGER_AUDIT_LIMIT, audit_inventory_ledger
from app.services.inventory_waste_service import list_inventory_waste_losses, record_inventory_waste_loss
from app.services.production_service import list_inventory_productions, process_inventory_production
from app.services.purchase_intake_service import MAX_PURCHASE_INTAKE_LIMIT, list_purchase_intakes, receive_purchase_intake
from app.services.planning_service import (
    get_inventory_planning,
    get_inventory_planning_item,
    list_critical_inventory_planning,
)
from app.services.access_service import authorize_restaurant, resolve_restaurant_access


router = APIRouter(prefix="/api/inventory", tags=["Inventory"])


@router.get("/items", response_model=list[InventoryItemRead])
def inventory_items(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.INVENTORY_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return list_inventory_items(db, restaurant_id=access.restaurant_id)


@router.post("/items", response_model=InventoryItemRead)
def inventory_item_create(
    payload: InventoryItemCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, payload.restaurant_id, Permission.INVENTORY_WRITE)
    return create_inventory_item(db, payload)


@router.patch("/items/{item_id}", response_model=InventoryItemRead)
def inventory_item_update(
    item_id: int,
    payload: InventoryItemUpdate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    item = require_inventory_item(db, item_id)
    authorize_restaurant(db, current_user, item.restaurant_id, Permission.INVENTORY_WRITE)
    return update_inventory_item(db, item_id, payload)


@router.post("/dish-ingredients", response_model=DishIngredientRead)
def dish_ingredient_create(
    payload: DishIngredientCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, payload.restaurant_id, Permission.INVENTORY_WRITE)
    return create_dish_ingredient(db, payload)


@router.post("/movements", response_model=InventoryMovementRead)
def inventory_movement_create(
    payload: InventoryMovementCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, payload.restaurant_id, Permission.INVENTORY_WRITE)
    return create_inventory_movement(db, payload)


@router.post("/purchase-intakes", response_model=PurchaseIntakeResult)
def inventory_purchase_intake_create(
    payload: PurchaseIntakeCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, payload.restaurant_id, Permission.INVENTORY_WRITE)
    return receive_purchase_intake(db, payload)


@router.get("/purchase-intakes", response_model=list[PurchaseIntakeRead])
def inventory_purchase_intakes(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    inventory_item_id: int | None = None,
    reference: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    is_valued: bool | None = None,
    limit: int = Query(default=100, ge=1, le=MAX_PURCHASE_INTAKE_LIMIT),
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.INVENTORY_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return list_purchase_intakes(
        db,
        restaurant_id=access.restaurant_id,
        inventory_item_id=inventory_item_id,
        reference=reference,
        start_date=start_date,
        end_date=end_date,
        is_valued=is_valued,
        limit=limit,
    )


@router.post("/adjustments", response_model=InventoryAdjustmentResult)
def inventory_adjustment_create(
    payload: InventoryAdjustmentCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, payload.restaurant_id, Permission.INVENTORY_WRITE)
    return record_inventory_adjustment(db, payload)


@router.get("/reconciliation", response_model=InventoryReconciliationResponse)
def inventory_reconciliation(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.INVENTORY_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return get_inventory_reconciliation(db, restaurant_id=access.restaurant_id)


@router.get("/ledger-audit", response_model=LedgerAuditResponse)
def inventory_ledger_audit(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    inventory_item_id: int | None = None,
    severity: str | None = None,
    code: str | None = None,
    limit: int = Query(default=100, ge=1, le=MAX_LEDGER_AUDIT_LIMIT),
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.INVENTORY_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return audit_inventory_ledger(
        db,
        restaurant_id=access.restaurant_id,
        inventory_item_id=inventory_item_id,
        severity=severity,
        code=code,
        limit=limit,
    )


@router.post("/waste-losses", response_model=InventoryWasteLossRead)
def inventory_waste_loss_create(
    payload: InventoryWasteLossCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, payload.restaurant_id, Permission.PRODUCTION_WRITE)
    return record_inventory_waste_loss(db, payload)


@router.get("/waste-losses", response_model=list[InventoryWasteLossRead])
def inventory_waste_losses(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.INVENTORY_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return list_inventory_waste_losses(db, restaurant_id=access.restaurant_id)


@router.post("/productions", response_model=InventoryProductionRead)
def inventory_production_create(
    payload: InventoryProductionCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, payload.restaurant_id, Permission.PRODUCTION_WRITE)
    return process_inventory_production(db, payload)


@router.get("/productions", response_model=list[InventoryProductionRead])
def inventory_productions(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.INVENTORY_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return list_inventory_productions(db, restaurant_id=access.restaurant_id)


@router.get("/alerts", response_model=list[InventoryAlertRead])
def inventory_alerts(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.INVENTORY_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return get_inventory_alerts(db, restaurant_id=access.restaurant_id)


@router.get("/insights", response_model=list[InventoryInsightRead])
def inventory_insights(
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
    return get_inventory_insights(db, restaurant_id=access.restaurant_id, range_value=range)


@router.get("/overview", response_model=InventoryOverview)
def inventory_overview(
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
    return get_inventory_overview(db, restaurant_id=access.restaurant_id, range_value=range)


@router.get("/planning", response_model=InventoryPlanningResponse)
def inventory_planning(
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
    return get_inventory_planning(db, restaurant_id=access.restaurant_id, range_value=range)


@router.get("/planning/critical", response_model=list[InventoryPlanningItem])
def inventory_planning_critical(
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
    return list_critical_inventory_planning(db, restaurant_id=access.restaurant_id, range_value=range)


@router.get("/planning/items/{item_id}", response_model=InventoryPlanningItem)
def inventory_planning_item(
    item_id: int,
    restaurant_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    range: str | None = None,
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, restaurant_id, Permission.INVENTORY_READ)
    return get_inventory_planning_item(db, restaurant_id=restaurant_id, item_id=item_id, range_value=range)
