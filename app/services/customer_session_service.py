import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.access import Permission
from app.core.customer import (
    CUSTOMER_SESSION_TTL_SECONDS,
    CustomerSessionStatus,
)
from app.core.dining import ServiceSessionStatus
from app.core.exceptions import AppError
from app.core.config import settings
from app.models import (
    CustomerSession,
    QRCode,
    RestaurantTable,
    ServiceSession,
    User,
)
from app.schemas.customer import TableQRCodeRead
from app.services.access_service import authorize_restaurant
from app.services.dining_room_service import require_table


def get_table_qr(
    db: Session,
    actor: User,
    restaurant_id: int,
    table_id: int,
) -> TableQRCodeRead:
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.CUSTOMER_QR_READ,
    )
    table = require_table(db, restaurant_id, table_id)
    qr_code = _active_table_qr(db, restaurant_id, table_id)
    if qr_code is None:
        raise AppError(
            "La mesa no tiene un QR de cliente activo.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="customer_qr_not_found",
        )
    return _qr_schema(qr_code, table)


def issue_table_qr(
    db: Session,
    actor: User,
    restaurant_id: int,
    table_id: int,
    *,
    rotate: bool,
) -> TableQRCodeRead:
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.CUSTOMER_QR_MANAGE,
    )
    table = require_table(db, restaurant_id, table_id)
    if not table.is_active:
        raise AppError(
            "No se puede generar un QR para una mesa inactiva.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_qr_table_inactive",
        )

    existing = _active_table_qr(db, restaurant_id, table_id)
    if existing is not None and not rotate:
        return _qr_schema(existing, table)

    now = datetime.utcnow()
    if existing is not None:
        existing.status = "revoked"
        existing.revoked_at = now
        existing.updated_at = now
        _revoke_table_customer_sessions(
            db,
            restaurant_id,
            table_id,
            now,
        )

    token = secrets.token_urlsafe(32)
    target_url = (
        f"{settings.app_url.rstrip('/')}/menu/table/{token}"
    )
    qr_code = QRCode(
        restaurant_id=restaurant_id,
        table_id=table_id,
        access_token=token,
        target_url=target_url,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(qr_code)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent = _active_table_qr(
            db,
            restaurant_id,
            table_id,
        )
        if concurrent is not None and not rotate:
            return _qr_schema(concurrent, table)
        raise AppError(
            "No se pudo generar el QR de la mesa.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_qr_conflict",
        ) from exc
    db.refresh(qr_code)
    return _qr_schema(qr_code, table)


def resolve_table_qr(
    db: Session,
    access_token: str,
) -> CustomerSession:
    qr_code = db.scalar(
        select(QRCode)
        .options(
            selectinload(QRCode.table),
            selectinload(QRCode.restaurant),
        )
        .where(
            QRCode.access_token == access_token,
            QRCode.status == "active",
            QRCode.table_id.is_not(None),
        )
    )
    if (
        qr_code is None
        or qr_code.table is None
        or qr_code.restaurant is None
        or not qr_code.table.is_active
        or not qr_code.restaurant.is_active
        or qr_code.table.restaurant_id != qr_code.restaurant_id
    ):
        raise AppError(
            "El QR no es valido o ha sido revocado.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="customer_qr_invalid",
        )

    service_session = db.scalar(
        select(ServiceSession).where(
            ServiceSession.restaurant_id == qr_code.restaurant_id,
            ServiceSession.table_id == qr_code.table_id,
            ServiceSession.status == ServiceSessionStatus.OPEN.value,
        )
    )
    if service_session is None:
        raise AppError(
            "La mesa no tiene un servicio abierto.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_table_not_in_service",
        )

    now = datetime.utcnow()
    existing = _active_customer_session(
        db,
        service_session.id,
    )
    if existing is not None and existing.expires_at > now:
        return existing
    if existing is not None:
        existing.status = CustomerSessionStatus.EXPIRED.value
        existing.last_activity_at = now
        db.flush()

    customer_session = CustomerSession(
        restaurant_id=qr_code.restaurant_id,
        table_id=qr_code.table_id,
        service_session_id=service_session.id,
        session_token=secrets.token_urlsafe(32),
        status=CustomerSessionStatus.ACTIVE.value,
        created_at=now,
        last_activity_at=now,
        expires_at=now
        + timedelta(seconds=CUSTOMER_SESSION_TTL_SECONDS),
    )
    db.add(customer_session)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent = _active_customer_session(
            db,
            service_session.id,
        )
        if concurrent is not None and concurrent.expires_at > now:
            return concurrent
        raise AppError(
            "No se pudo abrir la sesion de cliente.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_session_conflict",
        ) from exc
    return require_customer_session(
        db,
        customer_session.session_token,
    )


def require_customer_session(
    db: Session,
    session_token: str,
    *,
    lock: bool = False,
) -> CustomerSession:
    statement = (
        select(CustomerSession)
        .options(
            selectinload(CustomerSession.restaurant),
            selectinload(CustomerSession.table),
            selectinload(CustomerSession.service_session),
        )
        .where(CustomerSession.session_token == session_token)
    )
    if lock:
        statement = statement.with_for_update()
    customer_session = db.scalar(statement)
    if (
        customer_session is None
        or customer_session.status
        == CustomerSessionStatus.REVOKED.value
    ):
        raise AppError(
            "La sesion de cliente no es valida.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="customer_session_invalid",
        )
    if (
        customer_session.status
        == CustomerSessionStatus.EXPIRED.value
        or customer_session.expires_at <= datetime.utcnow()
    ):
        raise AppError(
            "La sesion de cliente ha expirado.",
            status_code=status.HTTP_410_GONE,
            code="customer_session_expired",
        )
    service_session = customer_session.service_session
    if (
        service_session is None
        or service_session.status != ServiceSessionStatus.OPEN.value
        or service_session.restaurant_id
        != customer_session.restaurant_id
        or service_session.table_id != customer_session.table_id
        or customer_session.restaurant is None
        or not customer_session.restaurant.is_active
        or customer_session.table is None
        or not customer_session.table.is_active
    ):
        raise AppError(
            "El servicio de mesa ya no esta disponible.",
            status_code=status.HTTP_410_GONE,
            code="customer_service_session_closed",
        )
    return customer_session


def touch_customer_session(
    customer_session: CustomerSession,
    now: datetime | None = None,
) -> None:
    customer_session.last_activity_at = now or datetime.utcnow()


def _active_customer_session(
    db: Session,
    service_session_id: int,
) -> CustomerSession | None:
    return db.scalar(
        select(CustomerSession).where(
            CustomerSession.service_session_id == service_session_id,
            CustomerSession.status
            == CustomerSessionStatus.ACTIVE.value,
        )
    )


def _active_table_qr(
    db: Session,
    restaurant_id: int,
    table_id: int,
) -> QRCode | None:
    return db.scalar(
        select(QRCode).where(
            QRCode.restaurant_id == restaurant_id,
            QRCode.table_id == table_id,
            QRCode.status == "active",
        )
    )


def _revoke_table_customer_sessions(
    db: Session,
    restaurant_id: int,
    table_id: int,
    now: datetime,
) -> None:
    db.execute(
        update(CustomerSession)
        .where(
            CustomerSession.restaurant_id == restaurant_id,
            CustomerSession.table_id == table_id,
            CustomerSession.status
            == CustomerSessionStatus.ACTIVE.value,
        )
        .values(
            status=CustomerSessionStatus.REVOKED.value,
            revoked_at=now,
            last_activity_at=now,
        )
        .execution_options(synchronize_session=False)
    )


def _qr_schema(
    qr_code: QRCode,
    table: RestaurantTable,
) -> TableQRCodeRead:
    return TableQRCodeRead(
        table_code=table.code,
        target_url=qr_code.target_url,
        status=qr_code.status,
        created_at=qr_code.created_at,
        updated_at=qr_code.updated_at,
    )
