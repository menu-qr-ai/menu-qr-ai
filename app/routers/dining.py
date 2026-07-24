from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from starlette import status

from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.dining import (
    DiningRoomState,
    RestaurantTableCreate,
    RestaurantTableRead,
    RestaurantTableUpdate,
    ServiceSessionOpen,
    ServiceSessionRead,
    ZoneCreate,
    ZoneRead,
    ZoneUpdate,
)
from app.schemas.customer import TableQRCodeIssue, TableQRCodeRead
from app.schemas.settlement import ServiceSessionSettlementRead
from app.services.dining_room_service import (
    create_table,
    create_zone,
    get_dining_room_state,
    list_tables,
    list_zones,
    update_table,
    update_zone,
)
from app.services.service_session_service import (
    cancel_service_session,
    close_service_session,
    get_service_session,
    open_service_session,
)
from app.services.service_session_settlement_service import (
    get_service_session_settlement,
    settle_service_session,
)
from app.services.customer_session_service import (
    get_table_qr,
    issue_table_qr,
)
from app.services.qr_service import build_qr_png_bytes


router = APIRouter(prefix="/api/dining/{restaurant_id}", tags=["Dining Room"])


@router.get(
    "/tables/{table_id}/customer-qr",
    response_model=TableQRCodeRead,
)
def table_customer_qr_detail(
    restaurant_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return get_table_qr(
        db,
        current_user,
        restaurant_id,
        table_id,
    )


@router.post(
    "/tables/{table_id}/customer-qr",
    response_model=TableQRCodeRead,
)
def table_customer_qr_issue(
    restaurant_id: int,
    table_id: int,
    payload: TableQRCodeIssue,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return issue_table_qr(
        db,
        current_user,
        restaurant_id,
        table_id,
        rotate=payload.rotate,
    )


@router.get("/tables/{table_id}/customer-qr.png")
def table_customer_qr_image(
    restaurant_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    qr_code = get_table_qr(
        db,
        current_user,
        restaurant_id,
        table_id,
    )
    return Response(
        content=build_qr_png_bytes(qr_code.target_url),
        media_type="image/png",
        headers={
            "Content-Disposition": (
                f'inline; filename="mesa-{table_id}-qr.png"'
            )
        },
    )


@router.get("/zones", response_model=list[ZoneRead])
def zones_index(
    restaurant_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return list_zones(db, current_user, restaurant_id, active_only=active_only)


@router.post("/zones", response_model=ZoneRead, status_code=status.HTTP_201_CREATED)
def zone_create(
    restaurant_id: int,
    payload: ZoneCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return create_zone(db, current_user, restaurant_id, payload)


@router.patch("/zones/{zone_id}", response_model=ZoneRead)
def zone_update(
    restaurant_id: int,
    zone_id: int,
    payload: ZoneUpdate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return update_zone(db, current_user, restaurant_id, zone_id, payload)


@router.get("/tables", response_model=list[RestaurantTableRead])
def tables_index(
    restaurant_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return list_tables(db, current_user, restaurant_id, active_only=active_only)


@router.post("/tables", response_model=RestaurantTableRead, status_code=status.HTTP_201_CREATED)
def table_create(
    restaurant_id: int,
    payload: RestaurantTableCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return create_table(db, current_user, restaurant_id, payload)


@router.patch("/tables/{table_id}", response_model=RestaurantTableRead)
def table_update(
    restaurant_id: int,
    table_id: int,
    payload: RestaurantTableUpdate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return update_table(db, current_user, restaurant_id, table_id, payload)


@router.get("/room", response_model=DiningRoomState)
def dining_room_state(
    restaurant_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return get_dining_room_state(db, current_user, restaurant_id)


@router.post(
    "/tables/{table_id}/sessions",
    response_model=ServiceSessionRead,
    status_code=status.HTTP_201_CREATED,
)
def service_session_open(
    restaurant_id: int,
    table_id: int,
    payload: ServiceSessionOpen,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return open_service_session(db, current_user, restaurant_id, table_id, payload)


@router.get("/sessions/{session_id}", response_model=ServiceSessionRead)
def service_session_detail(
    restaurant_id: int,
    session_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return get_service_session(db, current_user, restaurant_id, session_id)


@router.post("/sessions/{session_id}/close", response_model=ServiceSessionRead)
def service_session_close(
    restaurant_id: int,
    session_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return close_service_session(db, current_user, restaurant_id, session_id)


@router.post("/sessions/{session_id}/cancel", response_model=ServiceSessionRead)
def service_session_cancel(
    restaurant_id: int,
    session_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return cancel_service_session(db, current_user, restaurant_id, session_id)


@router.post(
    "/sessions/{session_id}/settle",
    response_model=ServiceSessionSettlementRead,
)
def service_session_settle(
    restaurant_id: int,
    session_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return settle_service_session(
        db,
        current_user,
        restaurant_id,
        session_id,
    )


@router.get(
    "/sessions/{session_id}/settlement",
    response_model=ServiceSessionSettlementRead,
)
def service_session_settlement_detail(
    restaurant_id: int,
    session_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return get_service_session_settlement(
        db,
        current_user,
        restaurant_id,
        session_id,
    )
