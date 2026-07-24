from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import require_web_user
from app.models import User
from app.services.waiter_workflow_service import get_waiter_workspace
from app.templates import templates


router = APIRouter(prefix="/staff/waiter", tags=["Waiter Workspace"])


@router.get("")
def waiter_workspace(
    request: Request,
    current_user: Annotated[User, Depends(require_web_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request=request,
        name="waiter/workspace.html",
        context=get_waiter_workspace(db, current_user, active_restaurant_id),
    )
