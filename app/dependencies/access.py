from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models import User
from app.services.access_service import get_membership, list_user_memberships


def get_active_restaurant_id(
    request: Request,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
) -> int | None:
    session: dict = request.state.session
    restaurant_id = session.get("active_restaurant_id")
    if isinstance(restaurant_id, int):
        membership = get_membership(db, current_user.id, restaurant_id)
        if membership is not None:
            return restaurant_id
        session.pop("active_restaurant_id", None)

    memberships = list_user_memberships(db, current_user.id)
    if len(memberships) == 1:
        restaurant_id = memberships[0].restaurant_id
        session["active_restaurant_id"] = restaurant_id
        return restaurant_id
    return None
