from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.admin_service import get_admin_dashboard_data
from app.templates import templates


router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("")
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context=get_admin_dashboard_data(db),
    )
