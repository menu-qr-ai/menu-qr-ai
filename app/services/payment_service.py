import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette import status

from app.core.access import Permission
from app.core.exceptions import AppError
from app.core.money import ZERO_MONEY, normalize_money
from app.core.payment import PaymentMethod, PaymentStatus
from app.core.settlement import SettlementStatus
from app.models import Payment, ServiceSessionSettlement, User
from app.schemas.payment import (
    PaymentBalanceRead,
    PaymentCreate,
    PaymentCreateRead,
    PaymentRead,
)
from app.services.access_service import authorize_restaurant


logger = logging.getLogger("app.payment")


@dataclass(frozen=True)
class _NormalizedPayment:
    amount: Decimal
    method: PaymentMethod
    currency: str | None
    reference: str | None
    idempotency_key: str


def create_payment(
    db: Session,
    actor: User,
    restaurant_id: int,
    settlement_id: int,
    payload: PaymentCreate,
) -> PaymentCreateRead:
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.PAYMENT_WRITE,
    )
    normalized = _normalize_payment(payload)
    logger.info(
        "payment_started restaurant_id=%s settlement_id=%s "
        "payment_id=None amount=%s currency=%s method=%s",
        restaurant_id,
        settlement_id,
        normalized.amount,
        normalized.currency or "settlement",
        normalized.method.value,
    )

    existing = _get_payment_by_idempotency_key(
        db,
        restaurant_id,
        normalized.idempotency_key,
    )
    if existing is not None:
        return _resolve_replay(db, existing, settlement_id, normalized)

    payment_id: int | None = None
    try:
        _serialize_sqlite_payment_write(
            db,
            actor,
            restaurant_id,
        )
        settlement = _claim_finalized_settlement(
            db,
            restaurant_id,
            settlement_id,
        )
        concurrent = _get_payment_by_idempotency_key(
            db,
            restaurant_id,
            normalized.idempotency_key,
        )
        if concurrent is not None:
            db.rollback()
            return _resolve_replay(
                db,
                concurrent,
                settlement_id,
                normalized,
            )

        currency = _resolve_currency(
            normalized.currency,
            settlement.currency,
        )
        balance = _build_balance(db, settlement)
        if balance.is_fully_paid:
            raise AppError(
                "El settlement ya esta completamente pagado.",
                status_code=status.HTTP_409_CONFLICT,
                code="payment_already_completed",
            )
        if normalized.amount > balance.amount_remaining:
            raise AppError(
                "El importe supera el saldo pendiente.",
                status_code=status.HTTP_409_CONFLICT,
                code="payment_amount_exceeds_remaining",
            )

        now = datetime.utcnow()
        payment = Payment(
            restaurant_id=restaurant_id,
            settlement_id=settlement.id,
            status=PaymentStatus.COMPLETED.value,
            method=normalized.method.value,
            amount=normalized.amount,
            currency=currency,
            reference=normalized.reference,
            idempotency_key=normalized.idempotency_key,
            created_by_user_id=actor.id,
            paid_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(payment)
        db.flush()
        payment_id = payment.id
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent = _get_payment_by_idempotency_key(
            db,
            restaurant_id,
            normalized.idempotency_key,
        )
        if concurrent is not None:
            return _resolve_replay(
                db,
                concurrent,
                settlement_id,
                normalized,
            )
        _raise_transaction_failed(
            restaurant_id,
            settlement_id,
            payment_id,
            exc,
        )
    except AppError as exc:
        db.rollback()
        logger.warning(
            "payment_failed restaurant_id=%s settlement_id=%s "
            "payment_id=%s error_code=%s",
            restaurant_id,
            settlement_id,
            payment_id,
            exc.code,
        )
        raise
    except Exception as exc:
        db.rollback()
        _raise_transaction_failed(
            restaurant_id,
            settlement_id,
            payment_id,
            exc,
        )

    completed = _require_payment(
        db,
        restaurant_id,
        payment_id,
    )
    result = _to_create_schema(
        db,
        completed,
        is_idempotent_replay=False,
    )
    logger.info(
        "payment_completed restaurant_id=%s settlement_id=%s "
        "payment_id=%s amount=%s currency=%s method=%s",
        restaurant_id,
        settlement_id,
        completed.id,
        completed.amount,
        completed.currency,
        completed.method,
    )
    return result


def list_payments(
    db: Session,
    actor: User,
    restaurant_id: int,
    settlement_id: int,
) -> list[PaymentRead]:
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.PAYMENT_READ,
    )
    settlement = _require_settlement(
        db,
        restaurant_id,
        settlement_id,
    )
    _validate_settlement_status(settlement)
    payments = db.scalars(
        select(Payment)
        .where(
            Payment.restaurant_id == restaurant_id,
            Payment.settlement_id == settlement.id,
        )
        .order_by(Payment.paid_at, Payment.id)
    ).all()
    return [_to_payment_schema(payment) for payment in payments]


def get_payment_balance(
    db: Session,
    actor: User,
    restaurant_id: int,
    settlement_id: int,
) -> PaymentBalanceRead:
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.PAYMENT_READ,
    )
    settlement = _require_settlement(
        db,
        restaurant_id,
        settlement_id,
    )
    _validate_settlement_status(settlement)
    return _build_balance(db, settlement)


def _claim_finalized_settlement(
    db: Session,
    restaurant_id: int,
    settlement_id: int,
) -> ServiceSessionSettlement:
    settlement = _require_settlement(
        db,
        restaurant_id,
        settlement_id,
    )
    _validate_settlement_status(settlement)
    result = db.execute(
        update(ServiceSessionSettlement)
        .where(
            ServiceSessionSettlement.id == settlement_id,
            ServiceSessionSettlement.restaurant_id == restaurant_id,
            ServiceSessionSettlement.status
            == SettlementStatus.FINALIZED.value,
        )
        .values(
            updated_at=ServiceSessionSettlement.updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise AppError(
            "El settlement no esta disponible para registrar pagos.",
            status_code=status.HTTP_409_CONFLICT,
            code="payment_settlement_not_finalized",
        )
    return settlement


def _serialize_sqlite_payment_write(
    db: Session,
    actor: User,
    restaurant_id: int,
) -> None:
    if db.get_bind().dialect.name != "sqlite":
        return
    db.rollback()
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.PAYMENT_WRITE,
    )


def _build_balance(
    db: Session,
    settlement: ServiceSessionSettlement,
) -> PaymentBalanceRead:
    total = normalize_money(
        settlement.total,
        field_name="total del settlement",
    )
    paid_value = db.scalar(
        select(func.sum(Payment.amount)).where(
            Payment.restaurant_id == settlement.restaurant_id,
            Payment.settlement_id == settlement.id,
            Payment.status == PaymentStatus.COMPLETED.value,
        )
    )
    amount_paid = normalize_money(
        paid_value if paid_value is not None else ZERO_MONEY,
        field_name="importe pagado",
    )
    if amount_paid > total:
        raise AppError(
            "El balance persistido del settlement no es valido.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="payment_transaction_failed",
        )
    amount_remaining = normalize_money(
        total - amount_paid,
        field_name="importe pendiente",
    )
    return PaymentBalanceRead(
        settlement_id=settlement.id,
        currency=settlement.currency,
        total=total,
        amount_paid=amount_paid,
        amount_remaining=amount_remaining,
        is_fully_paid=amount_remaining == ZERO_MONEY,
    )


def _normalize_payment(payload: PaymentCreate) -> _NormalizedPayment:
    try:
        amount = normalize_money(
            payload.amount,
            field_name="importe del pago",
        )
    except ValueError as exc:
        raise AppError(
            "El importe del pago no es valido.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="payment_amount_invalid",
        ) from exc
    if amount <= ZERO_MONEY:
        raise AppError(
            "El importe del pago debe ser mayor que cero.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="payment_amount_invalid",
        )

    method_value = payload.method.strip().lower()
    try:
        method = PaymentMethod(method_value)
    except ValueError as exc:
        raise AppError(
            "El metodo de pago no es valido.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="payment_method_invalid",
        ) from exc

    currency = None
    if payload.currency is not None:
        currency = _normalize_currency(payload.currency)
    reference = (
        payload.reference.strip()
        if payload.reference is not None
        else None
    )
    if reference == "":
        reference = None
    idempotency_key = payload.idempotency_key.strip()
    if not idempotency_key:
        raise AppError(
            "La clave de idempotencia es obligatoria.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="payment_idempotency_conflict",
        )
    return _NormalizedPayment(
        amount=amount,
        method=method,
        currency=currency,
        reference=reference,
        idempotency_key=idempotency_key,
    )


def _resolve_currency(
    requested: str | None,
    settlement_currency: str,
) -> str:
    currency = _normalize_currency(settlement_currency)
    if requested is not None and requested != currency:
        raise AppError(
            "La moneda del pago no coincide con el settlement.",
            status_code=status.HTTP_409_CONFLICT,
            code="payment_currency_mismatch",
        )
    return currency


def _normalize_currency(value: str) -> str:
    currency = value.strip().upper()
    if not 3 <= len(currency) <= 8:
        raise AppError(
            "La moneda del pago no es valida.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="payment_currency_mismatch",
        )
    return currency


def _require_settlement(
    db: Session,
    restaurant_id: int,
    settlement_id: int,
) -> ServiceSessionSettlement:
    settlement = db.scalar(
        select(ServiceSessionSettlement).where(
            ServiceSessionSettlement.id == settlement_id,
            ServiceSessionSettlement.restaurant_id == restaurant_id,
        )
    )
    if settlement is None:
        raise AppError(
            "Settlement no encontrado.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="payment_settlement_not_found",
        )
    return settlement


def _validate_settlement_status(
    settlement: ServiceSessionSettlement,
) -> None:
    if settlement.status != SettlementStatus.FINALIZED.value:
        raise AppError(
            "El settlement debe estar finalizado.",
            status_code=status.HTTP_409_CONFLICT,
            code="payment_settlement_not_finalized",
        )


def _get_payment_by_idempotency_key(
    db: Session,
    restaurant_id: int,
    idempotency_key: str,
) -> Payment | None:
    return db.scalar(
        select(Payment).where(
            Payment.restaurant_id == restaurant_id,
            Payment.idempotency_key == idempotency_key,
        )
    )


def _require_payment(
    db: Session,
    restaurant_id: int,
    payment_id: int | None,
) -> Payment:
    payment = db.scalar(
        select(Payment).where(
            Payment.id == payment_id,
            Payment.restaurant_id == restaurant_id,
        )
    )
    if payment is None:
        raise AppError(
            "Pago no encontrado.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="payment_not_found",
        )
    return payment


def _resolve_replay(
    db: Session,
    payment: Payment,
    settlement_id: int,
    normalized: _NormalizedPayment,
) -> PaymentCreateRead:
    if not _matches_replay(payment, settlement_id, normalized):
        logger.warning(
            "payment_conflict restaurant_id=%s settlement_id=%s "
            "payment_id=%s error_code=payment_idempotency_conflict",
            payment.restaurant_id,
            settlement_id,
            payment.id,
        )
        raise AppError(
            "La clave de idempotencia ya se uso con otros datos.",
            status_code=status.HTTP_409_CONFLICT,
            code="payment_idempotency_conflict",
        )
    logger.info(
        "payment_replay restaurant_id=%s settlement_id=%s "
        "payment_id=%s",
        payment.restaurant_id,
        payment.settlement_id,
        payment.id,
    )
    return _to_create_schema(
        db,
        payment,
        is_idempotent_replay=True,
    )


def _matches_replay(
    payment: Payment,
    settlement_id: int,
    normalized: _NormalizedPayment,
) -> bool:
    currency_matches = (
        normalized.currency is None
        or payment.currency == normalized.currency
    )
    return (
        payment.settlement_id == settlement_id
        and payment.amount == normalized.amount
        and payment.method == normalized.method.value
        and payment.reference == normalized.reference
        and currency_matches
    )


def _to_payment_schema(payment: Payment) -> PaymentRead:
    return PaymentRead(
        payment_id=payment.id,
        settlement_id=payment.settlement_id,
        status=payment.status,
        method=payment.method,
        amount=payment.amount,
        currency=payment.currency,
        reference=payment.reference,
        created_by_user_id=payment.created_by_user_id,
        paid_at=payment.paid_at,
    )


def _to_create_schema(
    db: Session,
    payment: Payment,
    *,
    is_idempotent_replay: bool,
) -> PaymentCreateRead:
    settlement = _require_settlement(
        db,
        payment.restaurant_id,
        payment.settlement_id,
    )
    return PaymentCreateRead(
        **_to_payment_schema(payment).model_dump(),
        is_idempotent_replay=is_idempotent_replay,
        balance=_build_balance(db, settlement),
    )


def _raise_transaction_failed(
    restaurant_id: int,
    settlement_id: int,
    payment_id: int | None,
    exc: Exception,
) -> None:
    logger.exception(
        "payment_failed restaurant_id=%s settlement_id=%s "
        "payment_id=%s error_code=payment_transaction_failed",
        restaurant_id,
        settlement_id,
        payment_id,
        exc_info=exc,
    )
    raise AppError(
        "No se pudo registrar el pago.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="payment_transaction_failed",
    ) from exc
