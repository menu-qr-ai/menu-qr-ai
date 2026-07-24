from sqlalchemy.orm import Session

from app.core.access import Permission
from app.models import User
from app.schemas.kitchen import KitchenTicketRead
from app.services.access_service import resolve_restaurant_access
from app.services.kitchen_ticket_service import list_kitchen_tickets


def get_kitchen_workspace(
    db: Session,
    actor: User,
    active_restaurant_id: int | None,
) -> dict:
    membership = resolve_restaurant_access(
        db,
        actor,
        None,
        Permission.KITCHEN_OPERATE,
        active_restaurant_id=active_restaurant_id,
    )
    tickets = [
        KitchenTicketRead.model_validate(ticket).model_dump(mode="json")
        for ticket in list_kitchen_tickets(
            db,
            actor,
            membership.restaurant_id,
            active_only=True,
        )
    ]
    return {
        "current_user": actor,
        "current_membership": membership,
        "restaurant": membership.restaurant,
        "tickets": tickets,
        "kitchen_bootstrap": {
            "restaurantId": membership.restaurant_id,
            "tickets": tickets,
            "pollIntervalMs": 20000,
        },
    }
