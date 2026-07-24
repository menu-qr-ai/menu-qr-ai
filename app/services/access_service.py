from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.access import Permission, RestaurantRole, role_has_permission, role_home_path
from app.core.exceptions import AppError
from app.models import Restaurant, RestaurantMembership, User
from app.schemas.membership import MembershipCreate, MembershipUpdate
from app.schemas.restaurant import RestaurantCreate
from app.services.restaurant_service import create_restaurant_record


_ACTIVE_RESTAURANT_NOT_PROVIDED = object()


def list_user_memberships(
    db: Session,
    user_id: int,
    *,
    active_only: bool = True,
) -> list[RestaurantMembership]:
    statement = (
        select(RestaurantMembership)
        .options(selectinload(RestaurantMembership.restaurant))
        .where(RestaurantMembership.user_id == user_id)
        .order_by(Restaurant.name, RestaurantMembership.id)
        .join(Restaurant, Restaurant.id == RestaurantMembership.restaurant_id)
    )
    if active_only:
        statement = statement.where(
            RestaurantMembership.is_active.is_(True),
            Restaurant.is_active.is_(True),
        )
    return list(db.scalars(statement).all())


def get_membership(
    db: Session,
    user_id: int,
    restaurant_id: int,
    *,
    active_only: bool = True,
) -> RestaurantMembership | None:
    statement = (
        select(RestaurantMembership)
        .options(selectinload(RestaurantMembership.restaurant))
        .where(
            RestaurantMembership.user_id == user_id,
            RestaurantMembership.restaurant_id == restaurant_id,
        )
    )
    if active_only:
        statement = statement.where(RestaurantMembership.is_active.is_(True))
    membership = db.scalar(statement)
    if membership is None or (active_only and not membership.restaurant.is_active):
        return None
    return membership


def authorize_restaurant(
    db: Session,
    user: User,
    restaurant_id: int,
    permission: Permission,
) -> RestaurantMembership:
    membership = get_membership(db, user.id, restaurant_id)
    if membership is None:
        raise AppError(
            "No tienes acceso a este restaurante.",
            status_code=status.HTTP_403_FORBIDDEN,
            code="restaurant_access_denied",
        )
    if not role_has_permission(membership.role, permission):
        raise AppError(
            "Tu rol no permite realizar esta accion.",
            status_code=status.HTTP_403_FORBIDDEN,
            code="permission_denied",
        )
    return membership


def resolve_restaurant_access(
    db: Session,
    user: User,
    requested_restaurant_id: int | None,
    permission: Permission,
    *,
    active_restaurant_id: int | None | object = _ACTIVE_RESTAURANT_NOT_PROVIDED,
) -> RestaurantMembership:
    restaurant_id = requested_restaurant_id
    if restaurant_id is None and active_restaurant_id is not _ACTIVE_RESTAURANT_NOT_PROVIDED:
        restaurant_id = active_restaurant_id if isinstance(active_restaurant_id, int) else None
    elif restaurant_id is None:
        restaurant_id = user.restaurant_id
    if restaurant_id is not None:
        return authorize_restaurant(db, user, restaurant_id, permission)

    memberships = list_user_memberships(db, user.id)
    if len(memberships) == 1:
        membership = memberships[0]
        if not role_has_permission(membership.role, permission):
            raise AppError(
                "Tu rol no permite realizar esta accion.",
                status_code=status.HTTP_403_FORBIDDEN,
                code="permission_denied",
            )
        return membership
    if not memberships:
        raise AppError(
            "No tienes acceso activo a ningun restaurante.",
            status_code=status.HTTP_403_FORBIDDEN,
            code="restaurant_access_denied",
        )
    raise AppError(
        "Selecciona un restaurante para continuar.",
        status_code=status.HTTP_409_CONFLICT,
        code="active_restaurant_required",
    )


def select_active_restaurant(
    db: Session,
    user: User,
    restaurant_id: int,
    session: dict,
) -> RestaurantMembership:
    membership = authorize_restaurant(db, user, restaurant_id, Permission.RESTAURANT_READ)
    session["active_restaurant_id"] = membership.restaurant_id
    return membership


def get_access_context(
    db: Session,
    user: User,
    active_restaurant_id: int | None,
) -> dict:
    memberships = list_user_memberships(db, user.id)
    membership = next(
        (
            candidate
            for candidate in memberships
            if candidate.restaurant_id == active_restaurant_id
        ),
        None,
    )
    next_url = role_home_path(membership.role) if membership is not None else "/app/restaurants"
    return {
        "user": user,
        "active_restaurant": membership.restaurant if membership is not None else None,
        "membership": membership,
        "available_restaurants": [
            {"restaurant": candidate.restaurant, "membership": candidate}
            for candidate in memberships
        ],
        "next_url": next_url,
    }


def create_or_reactivate_membership(
    db: Session,
    actor: User,
    restaurant_id: int,
    payload: MembershipCreate,
) -> RestaurantMembership:
    authorize_restaurant(db, actor, restaurant_id, Permission.MEMBERSHIP_MANAGE)
    target_user = db.get(User, payload.user_id)
    if target_user is None:
        raise AppError(
            "Usuario no encontrado.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
        )
    membership = get_membership(db, payload.user_id, restaurant_id, active_only=False)
    if membership is None:
        membership = RestaurantMembership(
            user_id=payload.user_id,
            restaurant_id=restaurant_id,
            role=payload.role.value,
            is_active=True,
            created_by_user_id=actor.id,
        )
        db.add(membership)
    else:
        membership.role = payload.role.value
        membership.is_active = True
    db.commit()
    db.refresh(membership)
    return membership


def create_restaurant_with_owner(
    db: Session,
    owner: User,
    payload: RestaurantCreate,
) -> Restaurant:
    if not any(
        membership.role == RestaurantRole.OWNER.value
        for membership in list_user_memberships(db, owner.id)
    ):
        raise AppError(
            "Solo un propietario puede crear otro restaurante.",
            status_code=status.HTTP_403_FORBIDDEN,
            code="permission_denied",
        )
    restaurant = create_restaurant_record(db, payload)
    membership = RestaurantMembership(
        user_id=owner.id,
        restaurant_id=restaurant.id,
        role=RestaurantRole.OWNER.value,
        is_active=True,
        created_by_user_id=owner.id,
    )
    db.add(membership)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def update_membership(
    db: Session,
    actor: User,
    restaurant_id: int,
    membership_id: int,
    payload: MembershipUpdate,
) -> RestaurantMembership:
    authorize_restaurant(db, actor, restaurant_id, Permission.MEMBERSHIP_MANAGE)
    membership = db.scalar(
        select(RestaurantMembership).where(
            RestaurantMembership.id == membership_id,
            RestaurantMembership.restaurant_id == restaurant_id,
        )
    )
    if membership is None:
        raise AppError(
            "Membresia no encontrada.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="membership_not_found",
        )
    next_role = payload.role.value if payload.role is not None else membership.role
    next_active = payload.is_active if payload.is_active is not None else membership.is_active
    if membership.role == RestaurantRole.OWNER.value and membership.is_active and (
        next_role != RestaurantRole.OWNER.value or not next_active
    ):
        _require_another_owner(db, restaurant_id, membership.id)
    membership.role = next_role
    membership.is_active = next_active
    db.commit()
    db.refresh(membership)
    return membership


def _require_another_owner(db: Session, restaurant_id: int, membership_id: int) -> None:
    owner_count = db.scalar(
        select(func.count())
        .select_from(RestaurantMembership)
        .where(
            RestaurantMembership.restaurant_id == restaurant_id,
            RestaurantMembership.role == RestaurantRole.OWNER.value,
            RestaurantMembership.is_active.is_(True),
            RestaurantMembership.id != membership_id,
        )
    )
    if not owner_count:
        raise AppError(
            "El restaurante debe conservar al menos un propietario activo.",
            status_code=status.HTTP_409_CONFLICT,
            code="last_owner_required",
        )
