from sqlalchemy.orm import Session

from app.utils.demo_seed import seed_demo_database


def seed_demo_data(db: Session) -> None:
    seed_demo_database(db)
