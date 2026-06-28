from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db


router = APIRouter(tags=["Health"])


@router.get("/test")
def legacy_health_check():
    return {"ok": True}


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    return {"status": "ok", "database": "ok"}
