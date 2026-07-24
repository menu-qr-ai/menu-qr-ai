from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_current_user
from app.dependencies.access import get_active_restaurant_id
from app.models import User
from app.schemas.membership import (
    AccessibleRestaurantRead,
    AccessContextRead,
    ActiveRestaurantSelection,
    MembershipCreate,
    MembershipUpdate,
    RestaurantMembershipRead,
)
from app.services.access_service import (
    create_or_reactivate_membership,
    get_access_context,
    list_user_memberships,
    select_active_restaurant,
    update_membership,
)


router = APIRouter(prefix="/api/access", tags=["Access"])


@router.get("/restaurants", response_model=list[AccessibleRestaurantRead])
def accessible_restaurants(
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return [
        {"restaurant": membership.restaurant, "membership": membership}
        for membership in list_user_memberships(db, current_user.id)
    ]


@router.get("/context", response_model=AccessContextRead)
def access_context(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    db: Session = Depends(get_db),
):
    return get_access_context(db, current_user, active_restaurant_id)


@router.put("/active-restaurant", response_model=AccessContextRead)
def active_restaurant_select(
    payload: ActiveRestaurantSelection,
    request: Request,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    membership = select_active_restaurant(
        db,
        current_user,
        payload.restaurant_id,
        request.state.session,
    )
    return get_access_context(db, current_user, membership.restaurant_id)


@router.post(
    "/restaurants/{restaurant_id}/memberships",
    response_model=RestaurantMembershipRead,
)
def membership_create(
    restaurant_id: int,
    payload: MembershipCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return create_or_reactivate_membership(db, current_user, restaurant_id, payload)


@router.patch(
    "/restaurants/{restaurant_id}/memberships/{membership_id}",
    response_model=RestaurantMembershipRead,
)
def membership_update(
    restaurant_id: int,
    membership_id: int,
    payload: MembershipUpdate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return update_membership(db, current_user, restaurant_id, membership_id, payload)
