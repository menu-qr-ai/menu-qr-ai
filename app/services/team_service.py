import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.access import Permission, RestaurantRole
from app.core.exceptions import AppError
from app.core.security import hash_password, verify_password
from app.models import RestaurantMembership, User
from app.schemas.membership import MembershipCreate
from app.schemas.team import PasswordChange, TeamMemberCreate
from app.services.access_service import authorize_restaurant, create_or_reactivate_membership
from app.services.auth_service import get_user_by_email

# Easy to read aloud or copy from a screen: no 0/O, 1/l/I.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROLE_ORDER = {role.value: index for index, role in enumerate(RestaurantRole)}


def generate_temporary_password() -> str:
    groups = ("".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(4)) for _ in range(3))
    return "-".join(groups)


def list_team(db: Session, actor: User, restaurant_id: int) -> list[dict]:
    authorize_restaurant(db, actor, restaurant_id, Permission.MEMBERSHIP_MANAGE)
    memberships = db.scalars(
        select(RestaurantMembership)
        .options(selectinload(RestaurantMembership.user))
        .where(RestaurantMembership.restaurant_id == restaurant_id)
    ).all()
    owned_restaurant_ids = _owned_restaurant_ids(db, actor)
    members = [_member(db, membership, actor, owned_restaurant_ids) for membership in memberships]
    return sorted(
        members,
        key=lambda member: (not member["is_active"], ROLE_ORDER.get(member["role"], 99), member["email"]),
    )


def add_team_member(
    db: Session,
    actor: User,
    restaurant_id: int,
    payload: TeamMemberCreate,
) -> dict:
    authorize_restaurant(db, actor, restaurant_id, Permission.MEMBERSHIP_MANAGE)
    user = get_user_by_email(db, payload.email)
    temporary_password = None
    if user is not None:
        # Existing identity (e.g. works in another venue): grant access only.
        # Never touch its password or name: that would hand over someone else's account.
        if not user.is_active:
            raise AppError(
                "Esa cuenta está desactivada y no puede recibir accesos.",
                status_code=status.HTTP_409_CONFLICT,
                code="user_inactive",
            )
        existing = db.scalar(
            select(RestaurantMembership).where(
                RestaurantMembership.user_id == user.id,
                RestaurantMembership.restaurant_id == restaurant_id,
                RestaurantMembership.is_active.is_(True),
            )
        )
        if existing is not None:
            raise AppError(
                "Esa persona ya forma parte del equipo. Cambia su rol desde la lista.",
                status_code=status.HTTP_409_CONFLICT,
                code="member_already_active",
            )
        membership = create_or_reactivate_membership(
            db,
            actor,
            restaurant_id,
            MembershipCreate(user_id=user.id, role=payload.role),
        )
    else:
        temporary_password = generate_temporary_password()
        user = User(
            email=payload.email,
            full_name=payload.full_name,
            hashed_password=hash_password(temporary_password),
            # Legacy compatibility fields; RestaurantMembership authorizes.
            role=payload.role.value,
            restaurant_id=restaurant_id,
            is_active=True,
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise AppError(
                "Ya existe una cuenta con ese email. Vuelve a intentarlo.",
                status_code=status.HTTP_409_CONFLICT,
                code="user_email_conflict",
            ) from exc
        membership = RestaurantMembership(
            user_id=user.id,
            restaurant_id=restaurant_id,
            role=payload.role.value,
            is_active=True,
            created_by_user_id=actor.id,
        )
        db.add(membership)
        db.commit()
        db.refresh(membership)

    return {
        "member": _member(db, membership, actor, _owned_restaurant_ids(db, actor)),
        "created_account": temporary_password is not None,
        "temporary_password": temporary_password,
    }


def reset_member_password(
    db: Session,
    actor: User,
    restaurant_id: int,
    membership_id: int,
) -> dict:
    authorize_restaurant(db, actor, restaurant_id, Permission.MEMBERSHIP_MANAGE)
    membership = db.scalar(
        select(RestaurantMembership)
        .options(selectinload(RestaurantMembership.user))
        .where(
            RestaurantMembership.id == membership_id,
            RestaurantMembership.restaurant_id == restaurant_id,
        )
    )
    if membership is None:
        raise AppError(
            "Miembro del equipo no encontrado.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="membership_not_found",
        )
    owned_restaurant_ids = _owned_restaurant_ids(db, actor)
    if not _can_reset_password(db, membership.user, actor, owned_restaurant_ids):
        raise AppError(
            "No puedes cambiar la contraseña de esta persona: también trabaja en locales que no son tuyos, o eres tú (usa «Cambiar mi contraseña»).",
            status_code=status.HTTP_403_FORBIDDEN,
            code="password_reset_not_allowed",
        )
    temporary_password = generate_temporary_password()
    membership.user.hashed_password = hash_password(temporary_password)
    db.commit()
    db.refresh(membership)
    return {
        "member": _member(db, membership, actor, owned_restaurant_ids),
        "temporary_password": temporary_password,
    }


def change_own_password(db: Session, user: User, payload: PasswordChange) -> None:
    stored_user = db.get(User, user.id)
    if stored_user is None or not verify_password(payload.current_password, stored_user.hashed_password):
        raise AppError(
            "La contraseña actual no es correcta.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="current_password_invalid",
        )
    if payload.new_password == payload.current_password:
        raise AppError(
            "La contraseña nueva tiene que ser distinta de la actual.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="password_unchanged",
        )
    stored_user.hashed_password = hash_password(payload.new_password)
    db.commit()


def _owned_restaurant_ids(db: Session, actor: User) -> set[int]:
    return set(
        db.scalars(
            select(RestaurantMembership.restaurant_id).where(
                RestaurantMembership.user_id == actor.id,
                RestaurantMembership.role == RestaurantRole.OWNER.value,
                RestaurantMembership.is_active.is_(True),
            )
        ).all()
    )


def _can_reset_password(db: Session, target: User, actor: User, owned_restaurant_ids: set[int]) -> bool:
    """Only for accounts living entirely inside venues the actor owns, and never the actor."""
    if target.id == actor.id:
        return False
    target_restaurant_ids = set(
        db.scalars(
            select(RestaurantMembership.restaurant_id).where(RestaurantMembership.user_id == target.id)
        ).all()
    )
    return bool(target_restaurant_ids) and target_restaurant_ids <= owned_restaurant_ids


def _member(db: Session, membership: RestaurantMembership, actor: User, owned_restaurant_ids: set[int]) -> dict:
    user = membership.user
    return {
        "membership_id": membership.id,
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": membership.role,
        "is_active": membership.is_active,
        "is_self": user.id == actor.id,
        "can_reset_password": _can_reset_password(db, user, actor, owned_restaurant_ids),
    }
