from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.access import Permission
from app.core.dining import ServiceSessionStatus
from app.core.exceptions import AppError
from app.models import RestaurantTable, ServiceSession, User, Zone
from app.schemas.dining import (
    DiningRoomState,
    DiningRoomTableState,
    RestaurantTableCreate,
    RestaurantTableUpdate,
    ZoneCreate,
    ZoneUpdate,
)
from app.services.access_service import authorize_restaurant


def list_zones(
    db: Session,
    actor: User,
    restaurant_id: int,
    *,
    active_only: bool = False,
) -> list[Zone]:
    authorize_restaurant(db, actor, restaurant_id, Permission.DINING_ROOM_READ)
    statement = (
        select(Zone)
        .where(Zone.restaurant_id == restaurant_id)
        .order_by(Zone.display_order, Zone.name, Zone.id)
    )
    if active_only:
        statement = statement.where(Zone.is_active.is_(True))
    return list(db.scalars(statement).all())


def create_zone(
    db: Session,
    actor: User,
    restaurant_id: int,
    payload: ZoneCreate,
) -> Zone:
    authorize_restaurant(db, actor, restaurant_id, Permission.DINING_ROOM_MANAGE)
    _ensure_zone_name_available(db, restaurant_id, payload.name)
    zone = Zone(restaurant_id=restaurant_id, **payload.model_dump())
    db.add(zone)
    _commit_or_conflict(db, "Ya existe una zona con ese nombre.", "zone_name_conflict")
    db.refresh(zone)
    return zone


def update_zone(
    db: Session,
    actor: User,
    restaurant_id: int,
    zone_id: int,
    payload: ZoneUpdate,
) -> Zone:
    authorize_restaurant(db, actor, restaurant_id, Permission.DINING_ROOM_MANAGE)
    zone = require_zone(db, restaurant_id, zone_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        _ensure_zone_name_available(db, restaurant_id, data["name"], zone_id=zone.id)
    for field, value in data.items():
        setattr(zone, field, value)
    zone.updated_at = datetime.utcnow()
    _commit_or_conflict(db, "Ya existe una zona con ese nombre.", "zone_name_conflict")
    db.refresh(zone)
    return zone


def list_tables(
    db: Session,
    actor: User,
    restaurant_id: int,
    *,
    active_only: bool = False,
) -> list[RestaurantTable]:
    authorize_restaurant(db, actor, restaurant_id, Permission.DINING_ROOM_READ)
    statement = (
        select(RestaurantTable)
        .where(RestaurantTable.restaurant_id == restaurant_id)
        .order_by(RestaurantTable.display_order, RestaurantTable.code, RestaurantTable.id)
    )
    if active_only:
        statement = statement.where(RestaurantTable.is_active.is_(True))
    return list(db.scalars(statement).all())


def create_table(
    db: Session,
    actor: User,
    restaurant_id: int,
    payload: RestaurantTableCreate,
) -> RestaurantTable:
    authorize_restaurant(db, actor, restaurant_id, Permission.DINING_ROOM_MANAGE)
    _ensure_table_code_available(db, restaurant_id, payload.code)
    _validate_table_zone(
        db,
        restaurant_id,
        payload.zone_id,
        require_active=payload.is_active,
    )
    table = RestaurantTable(restaurant_id=restaurant_id, **payload.model_dump())
    db.add(table)
    _commit_or_conflict(db, "Ya existe una mesa con ese codigo.", "table_code_conflict")
    db.refresh(table)
    return table


def update_table(
    db: Session,
    actor: User,
    restaurant_id: int,
    table_id: int,
    payload: RestaurantTableUpdate,
) -> RestaurantTable:
    authorize_restaurant(db, actor, restaurant_id, Permission.DINING_ROOM_MANAGE)
    table = require_table(db, restaurant_id, table_id)
    data = payload.model_dump(exclude_unset=True)
    next_zone_id = data.get("zone_id", table.zone_id)
    next_is_active = data.get("is_active", table.is_active)
    _validate_table_zone(
        db,
        restaurant_id,
        next_zone_id,
        require_active=next_is_active,
    )
    if data.get("code") is not None:
        _ensure_table_code_available(db, restaurant_id, data["code"], table_id=table.id)
    if data.get("is_active") is False and _open_session_for_table(db, table.id) is not None:
        raise AppError(
            "No se puede desactivar una mesa con una sesion abierta.",
            status_code=status.HTTP_409_CONFLICT,
            code="table_has_open_session",
        )
    for field, value in data.items():
        setattr(table, field, value)
    table.updated_at = datetime.utcnow()
    _commit_or_conflict(db, "Ya existe una mesa con ese codigo.", "table_code_conflict")
    db.refresh(table)
    return table


def get_dining_room_state(
    db: Session,
    actor: User,
    restaurant_id: int,
) -> DiningRoomState:
    authorize_restaurant(db, actor, restaurant_id, Permission.DINING_ROOM_READ)
    zones = list(
        db.scalars(
            select(Zone)
            .where(Zone.restaurant_id == restaurant_id, Zone.is_active.is_(True))
            .order_by(Zone.display_order, Zone.name, Zone.id)
        ).all()
    )
    tables = list(
        db.scalars(
            select(RestaurantTable)
            .options(selectinload(RestaurantTable.zone))
            .where(
                RestaurantTable.restaurant_id == restaurant_id,
                RestaurantTable.is_active.is_(True),
            )
            .order_by(
                RestaurantTable.zone_id,
                RestaurantTable.display_order,
                RestaurantTable.code,
                RestaurantTable.id,
            )
        ).all()
    )
    sessions = list(
        db.scalars(
            select(ServiceSession)
            .options(selectinload(ServiceSession.opened_by))
            .where(
                ServiceSession.restaurant_id == restaurant_id,
                ServiceSession.status == ServiceSessionStatus.OPEN.value,
            )
        ).all()
    )
    sessions_by_table = {session.table_id: session for session in sessions}
    states = [
        DiningRoomTableState(
            table=table,
            zone=table.zone,
            is_occupied=table.id in sessions_by_table,
            current_session=sessions_by_table.get(table.id),
            responsible_user_name=(
                sessions_by_table[table.id].opened_by.full_name
                or sessions_by_table[table.id].opened_by.email
                if table.id in sessions_by_table
                else None
            ),
        )
        for table in tables
    ]
    occupied_tables = sum(state.is_occupied for state in states)
    return DiningRoomState(
        restaurant_id=restaurant_id,
        zones=zones,
        tables=states,
        free_tables=len(states) - occupied_tables,
        occupied_tables=occupied_tables,
    )


def require_zone(db: Session, restaurant_id: int, zone_id: int) -> Zone:
    zone = db.scalar(
        select(Zone).where(
            Zone.id == zone_id,
            Zone.restaurant_id == restaurant_id,
        )
    )
    if zone is None:
        raise AppError(
            "Zona no encontrada para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="zone_not_found",
        )
    return zone


def require_table(
    db: Session,
    restaurant_id: int,
    table_id: int,
) -> RestaurantTable:
    table = db.scalar(
        select(RestaurantTable).where(
            RestaurantTable.id == table_id,
            RestaurantTable.restaurant_id == restaurant_id,
        )
    )
    if table is None:
        raise AppError(
            "Mesa no encontrada para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="table_not_found",
        )
    return table


def _validate_table_zone(
    db: Session,
    restaurant_id: int,
    zone_id: int | None,
    *,
    require_active: bool,
) -> Zone | None:
    if zone_id is None:
        return None
    zone = require_zone(db, restaurant_id, zone_id)
    if require_active and not zone.is_active:
        raise AppError(
            "No se puede asignar una mesa activa a una zona inactiva.",
            status_code=status.HTTP_409_CONFLICT,
            code="zone_inactive",
        )
    return zone


def _ensure_zone_name_available(
    db: Session,
    restaurant_id: int,
    name: str,
    *,
    zone_id: int | None = None,
) -> None:
    statement = select(Zone.id).where(
        Zone.restaurant_id == restaurant_id,
        func.lower(Zone.name) == name.lower(),
    )
    if zone_id is not None:
        statement = statement.where(Zone.id != zone_id)
    if db.scalar(statement) is not None:
        raise AppError(
            "Ya existe una zona con ese nombre.",
            status_code=status.HTTP_409_CONFLICT,
            code="zone_name_conflict",
        )


def _ensure_table_code_available(
    db: Session,
    restaurant_id: int,
    code: str,
    *,
    table_id: int | None = None,
) -> None:
    statement = select(RestaurantTable.id).where(
        RestaurantTable.restaurant_id == restaurant_id,
        func.lower(RestaurantTable.code) == code.lower(),
    )
    if table_id is not None:
        statement = statement.where(RestaurantTable.id != table_id)
    if db.scalar(statement) is not None:
        raise AppError(
            "Ya existe una mesa con ese codigo.",
            status_code=status.HTTP_409_CONFLICT,
            code="table_code_conflict",
        )


def _open_session_for_table(
    db: Session,
    table_id: int,
) -> ServiceSession | None:
    return db.scalar(
        select(ServiceSession).where(
            ServiceSession.table_id == table_id,
            ServiceSession.status == ServiceSessionStatus.OPEN.value,
        )
    )


def _commit_or_conflict(
    db: Session,
    message: str,
    code: str,
) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            message,
            status_code=status.HTTP_409_CONFLICT,
            code=code,
        ) from exc
