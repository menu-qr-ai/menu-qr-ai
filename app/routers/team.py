from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette import status

from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.team import TeamMemberCreate, TeamMemberCreated, TeamMemberRead, TemporaryPasswordRead
from app.services.team_service import add_team_member, list_team, reset_member_password


router = APIRouter(prefix="/api/restaurants/{restaurant_id}/team", tags=["Team"])


@router.get("", response_model=list[TeamMemberRead])
def team_index(
    restaurant_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return list_team(db, current_user, restaurant_id)


@router.post("", response_model=TeamMemberCreated, status_code=status.HTTP_201_CREATED)
def team_member_create(
    restaurant_id: int,
    payload: TeamMemberCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return add_team_member(db, current_user, restaurant_id, payload)


@router.post("/{membership_id}/reset-password", response_model=TemporaryPasswordRead)
def team_member_reset_password(
    restaurant_id: int,
    membership_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return reset_member_password(db, current_user, restaurant_id, membership_id)
