from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access import Permission
from app.core.orders import ACTIVE_ORDER_STATUSES
from app.models import Order, User
from app.schemas.dining import DiningRoomState
from app.services.access_service import resolve_restaurant_access
from app.services.dining_room_service import get_dining_room_state
from app.services.menu_service import get_menu_data


def get_waiter_workspace(
    db: Session,
    actor: User,
    active_restaurant_id: int | None,
) -> dict:
    membership = resolve_restaurant_access(
        db,
        actor,
        None,
        Permission.SERVICE_SESSION_WRITE,
        active_restaurant_id=active_restaurant_id,
    )
    restaurant_id = membership.restaurant_id
    room = DiningRoomState.model_validate(
        get_dining_room_state(db, actor, restaurant_id)
    ).model_dump(mode="json")
    active_order_counts = dict(
        db.execute(
            select(Order.service_session_id, func.count(Order.id))
            .where(
                Order.restaurant_id == restaurant_id,
                Order.status.in_(ACTIVE_ORDER_STATUSES),
            )
            .group_by(Order.service_session_id)
        ).all()
    )
    for table_state in room["tables"]:
        current_session = table_state["current_session"]
        table_state["active_order_count"] = (
            active_order_counts.get(current_session["id"], 0)
            if current_session is not None
            else 0
        )

    menu = get_menu_data(db, restaurant_id)
    bootstrap = {
        "restaurantId": restaurant_id,
        "currency": membership.restaurant.currency or "EUR",
        "room": room,
        "categories": menu["categories"],
        "dishes": menu["dishes"],
    }
    return {
        "current_user": actor,
        "current_membership": membership,
        "restaurant": membership.restaurant,
        "room": room,
        "waiter_bootstrap": bootstrap,
    }
