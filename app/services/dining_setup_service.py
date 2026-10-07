from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import Permission
from app.core.config import settings
from app.core.dining import ServiceSessionStatus
from app.models import QRCode, RestaurantTable, ServiceSession, User, Zone
from app.services.access_service import authorize_restaurant

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def customer_qr_reachable_from_phones() -> bool:
    """QR codes embed APP_URL; a loopback host only works on this computer."""
    host = (urlparse(settings.app_url).hostname or "").lower()
    return bool(host) and host not in LOCAL_HOSTS


def get_dining_setup(db: Session, actor: User, restaurant_id: int) -> dict:
    """Room configuration for owners/managers, inactive zones and tables included.

    QR tokens are bearer credentials, so only the QR status leaves this function.
    """
    authorize_restaurant(db, actor, restaurant_id, Permission.DINING_ROOM_MANAGE)
    zones = db.scalars(
        select(Zone)
        .where(Zone.restaurant_id == restaurant_id)
        .order_by(Zone.display_order, Zone.name, Zone.id)
    ).all()
    tables = db.scalars(
        select(RestaurantTable)
        .where(RestaurantTable.restaurant_id == restaurant_id)
        .order_by(RestaurantTable.display_order, RestaurantTable.code, RestaurantTable.id)
    ).all()
    tables_with_qr = set(
        db.scalars(
            select(QRCode.table_id).where(
                QRCode.restaurant_id == restaurant_id,
                QRCode.table_id.is_not(None),
                QRCode.status == "active",
            )
        ).all()
    )
    tables_with_open_session = set(
        db.scalars(
            select(ServiceSession.table_id).where(
                ServiceSession.restaurant_id == restaurant_id,
                ServiceSession.status == ServiceSessionStatus.OPEN.value,
            )
        ).all()
    )
    return {
        "restaurant_id": restaurant_id,
        "qr_reachable_from_phones": customer_qr_reachable_from_phones(),
        "zones": [
            {
                "id": zone.id,
                "name": zone.name,
                "display_order": zone.display_order,
                "is_active": zone.is_active,
            }
            for zone in zones
        ],
        "tables": [
            {
                "id": table.id,
                "zone_id": table.zone_id,
                "code": table.code,
                "capacity": table.capacity,
                "display_order": table.display_order,
                "is_active": table.is_active,
                "has_customer_qr": table.id in tables_with_qr,
                "has_open_session": table.id in tables_with_open_session,
            }
            for table in tables
        ],
    }


def get_printable_table_qrs(db: Session, actor: User, restaurant_id: int) -> list[dict]:
    """Active tables that already have a customer QR, in room order, for printing."""
    authorize_restaurant(db, actor, restaurant_id, Permission.CUSTOMER_QR_MANAGE)
    rows = db.execute(
        select(RestaurantTable, Zone.name)
        .join(QRCode, (QRCode.table_id == RestaurantTable.id) & (QRCode.status == "active"))
        .outerjoin(Zone, Zone.id == RestaurantTable.zone_id)
        .where(
            RestaurantTable.restaurant_id == restaurant_id,
            RestaurantTable.is_active.is_(True),
        )
        .order_by(Zone.display_order, RestaurantTable.display_order, RestaurantTable.code)
    ).all()
    return [
        {"id": table.id, "code": table.code, "zone_name": zone_name}
        for table, zone_name in rows
    ]
