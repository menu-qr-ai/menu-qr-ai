from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.restaurant import RestaurantRead
from app.services.access_service import list_user_memberships


router = APIRouter(prefix="/restaurants", tags=["Restaurants"])


@router.get("", response_model=list[RestaurantRead])
def restaurants_index(
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return [membership.restaurant for membership in list_user_memberships(db, current_user.id)]
