import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import AppError
from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    AnalyticsEvent,
    InventoryItem,
    InventoryMovement,
    Order,
    OrderFulfillment,
    Payment,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    ServiceSessionSettlement,
    User,
)
from app.schemas.payment import PaymentCreate
from app.services.payment_service import (
    _validate_settlement_status,
    create_payment,
)


class PaymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/payments.db",
            connect_args={
                "check_same_thread": False,
                "timeout": 30,
            },
        )
        cls.SessionTesting = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=cls.engine,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls._seed_access()

        def override_get_db():
            db = cls.SessionTesting()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()
        cls.temp_dir.cleanup()

    @classmethod
    def _seed_access(cls):
        with cls.SessionTesting() as db:
            db.add_all(
                [
                    Restaurant(
                        id=101,
                        name="Payments Centro",
                        slug="payments-centro",
                        currency="EUR",
                    ),
                    Restaurant(
                        id=102,
                        name="Payments Playa",
                        slug="payments-playa",
                        currency="EUR",
                    ),
                ]
            )
            roles = ("owner", "manager", "waiter", "cook", "viewer")
            for offset, role in enumerate(roles, start=1):
                user_id = 100 + offset
                db.add(
                    User(
                        id=user_id,
                        email=f"payment-{role}@hostai.test",
                        hashed_password="not-used",
                        full_name=f"Payment {role.title()}",
                        role=role,
                        restaurant_id=101,
                        is_active=True,
                    )
                )
                db.add(
                    RestaurantMembership(
                        user_id=user_id,
                        restaurant_id=101,
                        role=role,
                        is_active=True,
                        created_by_user_id=101,
                    )
                )
            db.add(
                RestaurantMembership(
                    user_id=101,
                    restaurant_id=102,
                    role="owner",
                    is_active=True,
                    created_by_user_id=101,
                )
            )
            db.commit()

    def setUp(self):
        self.key_counter = 0
        with self.SessionTesting() as db:
            db.execute(delete(Payment))
            db.execute(delete(ServiceSessionSettlement))
            db.execute(delete(ServiceSession))
            db.execute(delete(RestaurantTable))
            db.execute(delete(InventoryMovement))
            db.execute(delete(InventoryItem))
            db.execute(
                RestaurantMembership.__table__.update().values(
                    is_active=True
                )
            )
            db.execute(
                Restaurant.__table__.update().values(currency="EUR")
            )
            db.commit()

            self.settlement_ids: dict[int, int] = {}
            self.session_ids: dict[int, int] = {}
            self.table_ids: dict[int, int] = {}
            for restaurant_id, total in (
                (101, Decimal("100.00")),
                (102, Decimal("50.00")),
            ):
                settlement = self._insert_settlement(
                    db,
                    restaurant_id=restaurant_id,
                    total=total,
                )
                self.settlement_ids[restaurant_id] = settlement.id
                self.session_ids[restaurant_id] = (
                    settlement.service_session_id
                )
                service_session = db.get(
                    ServiceSession,
                    settlement.service_session_id,
                )
                self.table_ids[restaurant_id] = service_session.table_id
            inventory = InventoryItem(
                restaurant_id=101,
                name="Payment invariant stock",
                unit="unit",
                current_stock=12.5,
                minimum_stock=0,
                ideal_stock=20,
                cost=3,
            )
            db.add(inventory)
            db.commit()
            self.inventory_id = inventory.id

    def _insert_settlement(
        self,
        db,
        *,
        restaurant_id: int = 101,
        total: Decimal = Decimal("100.00"),
    ) -> ServiceSessionSettlement:
        ordinal = db.scalar(
            select(func.count())
            .select_from(RestaurantTable)
            .where(RestaurantTable.restaurant_id == restaurant_id)
        )
        now = datetime.utcnow()
        table = RestaurantTable(
            restaurant_id=restaurant_id,
            code=f"P-{restaurant_id}-{ordinal + 1}",
            capacity=4,
        )
        db.add(table)
        db.flush()
        actor_id = 101
        service_session = ServiceSession(
            restaurant_id=restaurant_id,
            table_id=table.id,
            status="closed",
            opened_at=now,
            closed_at=now,
            guest_count=2,
            opened_by_user_id=actor_id,
            closed_by_user_id=actor_id,
            created_at=now,
            updated_at=now,
        )
        db.add(service_session)
        db.flush()
        settlement = ServiceSessionSettlement(
            restaurant_id=restaurant_id,
            service_session_id=service_session.id,
            status="finalized",
            idempotency_key=(
                f"payment-test-settlement:{restaurant_id}:"
                f"{service_session.id}"
            ),
            currency="EUR",
            subtotal=total,
            total=total,
            created_by_user_id=actor_id,
            finalized_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(settlement)
        db.flush()
        return settlement

    @contextmanager
    def client_as(
        self,
        user_id: int,
        *,
        active_restaurant_id: int = 101,
    ):
        role = {
            101: "owner",
            102: "manager",
            103: "waiter",
            104: "cook",
            105: "viewer",
        }[user_id]
        user = User(
            id=user_id,
            email=f"payment-{role}@hostai.test",
            hashed_password="not-used",
            full_name=f"Payment {role.title()}",
            role=role,
            restaurant_id=active_restaurant_id,
            is_active=True,
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_active_restaurant_id] = (
            lambda: active_restaurant_id
        )
        try:
            with TestClient(
                app,
                raise_server_exceptions=False,
            ) as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(
                get_active_restaurant_id,
                None,
            )

    def _key(self, prefix: str = "payment") -> str:
        self.key_counter += 1
        return f"{prefix}-{self.key_counter}"

    def _post_payment(
        self,
        client: TestClient,
        *,
        amount: str = "100.00",
        method: str = "cash",
        currency: str | None = "EUR",
        reference: str | None = None,
        idempotency_key: str | None = None,
        restaurant_id: int = 101,
        settlement_id: int | None = None,
    ):
        body = {
            "amount": amount,
            "method": method,
            "reference": reference,
            "idempotency_key": idempotency_key or self._key(),
        }
        if currency is not None:
            body["currency"] = currency
        selected_settlement = (
            settlement_id or self.settlement_ids[restaurant_id]
        )
        return client.post(
            f"/api/dining/{restaurant_id}/settlements/"
            f"{selected_settlement}/payments",
            json=body,
        )

    def _balance(
        self,
        client: TestClient,
        *,
        restaurant_id: int = 101,
        settlement_id: int | None = None,
    ):
        selected_settlement = (
            settlement_id or self.settlement_ids[restaurant_id]
        )
        return client.get(
            f"/api/dining/{restaurant_id}/settlements/"
            f"{selected_settlement}/balance"
        )

    def _payment_effects(self) -> dict:
        with self.SessionTesting() as db:
            settlement = db.get(
                ServiceSessionSettlement,
                self.settlement_ids[101],
            )
            service_session = db.get(
                ServiceSession,
                self.session_ids[101],
            )
            return {
                "payments": db.scalar(
                    select(func.count()).select_from(Payment)
                ),
                "paid": db.scalar(
                    select(func.sum(Payment.amount)).where(
                        Payment.status == "completed"
                    )
                )
                or Decimal("0.00"),
                "settlement": (
                    settlement.total,
                    settlement.currency,
                    settlement.status,
                    settlement.updated_at,
                ),
                "session": (
                    service_session.status,
                    service_session.closed_at,
                    service_session.closed_by_user_id,
                ),
                "open_sessions": db.scalar(
                    select(func.count())
                    .select_from(ServiceSession)
                    .where(
                        ServiceSession.table_id == self.table_ids[101],
                        ServiceSession.status == "open",
                    )
                ),
                "stock": db.get(
                    InventoryItem,
                    self.inventory_id,
                ).current_stock,
                "movements": db.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                ),
                "analytics": db.scalar(
                    select(func.count()).select_from(AnalyticsEvent)
                ),
                "fulfillments": db.scalar(
                    select(func.count())
                    .select_from(OrderFulfillment)
                ),
                "orders": db.scalar(
                    select(func.count()).select_from(Order)
                ),
            }

    def test_initial_partial_mixed_and_full_balance(self):
        with self.client_as(103) as waiter:
            initial = self._balance(waiter)
            self.assertEqual(initial.status_code, 200, initial.text)
            self.assertEqual(
                initial.json(),
                {
                    "settlement_id": self.settlement_ids[101],
                    "currency": "EUR",
                    "total": "100.00",
                    "amount_paid": "0.00",
                    "amount_remaining": "100.00",
                    "is_fully_paid": False,
                },
            )

            cash = self._post_payment(
                waiter,
                amount="40.00",
                method="cash",
                reference="cash-partial",
            )
            self.assertEqual(cash.status_code, 201, cash.text)
            self.assertEqual(cash.json()["amount"], "40.00")
            self.assertEqual(cash.json()["method"], "cash")
            self.assertEqual(cash.json()["currency"], "EUR")
            self.assertFalse(cash.json()["is_idempotent_replay"])
            self.assertEqual(
                cash.json()["balance"]["amount_remaining"],
                "60.00",
            )

            card = self._post_payment(
                waiter,
                amount="60.00",
                method="card",
            )
            self.assertEqual(card.status_code, 201, card.text)
            self.assertEqual(card.json()["balance"]["amount_paid"], "100.00")
            self.assertEqual(
                card.json()["balance"]["amount_remaining"],
                "0.00",
            )
            self.assertTrue(card.json()["balance"]["is_fully_paid"])

            payments = waiter.get(
                f"/api/dining/101/settlements/"
                f"{self.settlement_ids[101]}/payments"
            )
            self.assertEqual(payments.status_code, 200, payments.text)
            self.assertEqual(
                [item["method"] for item in payments.json()],
                ["cash", "card"],
            )
            self.assertEqual(
                [item["amount"] for item in payments.json()],
                ["40.00", "60.00"],
            )

            extra = self._post_payment(
                waiter,
                amount="0.01",
                method="other",
            )
            self.assertEqual(extra.status_code, 409, extra.text)
            self.assertEqual(
                extra.json()["error"]["code"],
                "payment_already_completed",
            )

    def test_decimal_exactness_two_decimals_and_other_method(self):
        with self.SessionTesting() as db:
            settlement = db.get(
                ServiceSessionSettlement,
                self.settlement_ids[101],
            )
            settlement.subtotal = Decimal("0.30")
            settlement.total = Decimal("0.30")
            db.commit()

        with self.client_as(103) as waiter:
            first = self._post_payment(
                waiter,
                amount="0.10",
                method="other",
                reference=None,
            )
            second = self._post_payment(
                waiter,
                amount="0.20",
                method="cash",
            )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertIsNone(first.json()["reference"])
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.json()["balance"]["amount_paid"], "0.30")
        self.assertEqual(
            second.json()["balance"]["amount_remaining"],
            "0.00",
        )

    def test_invalid_amounts_methods_currency_and_overpayment(self):
        invalid_amounts = (
            "0.00",
            "-0.01",
            "NaN",
            "Infinity",
            "1.001",
            "10000000000.00",
        )
        with self.client_as(103) as waiter:
            for amount in invalid_amounts:
                with self.subTest(amount=amount):
                    response = self._post_payment(
                        waiter,
                        amount=amount,
                    )
                    self.assertEqual(
                        response.status_code,
                        422,
                        response.text,
                    )
                    self.assertEqual(
                        response.json()["error"]["code"],
                        "payment_amount_invalid",
                    )

            invalid_method = self._post_payment(
                waiter,
                amount="1.00",
                method="bizum",
            )
            self.assertEqual(invalid_method.status_code, 422)
            self.assertEqual(
                invalid_method.json()["error"]["code"],
                "payment_method_invalid",
            )

            invalid_currency = self._post_payment(
                waiter,
                amount="1.00",
                currency="USD",
            )
            self.assertEqual(invalid_currency.status_code, 409)
            self.assertEqual(
                invalid_currency.json()["error"]["code"],
                "payment_currency_mismatch",
            )

            overpayment = self._post_payment(
                waiter,
                amount="100.01",
            )
            self.assertEqual(overpayment.status_code, 409)
            self.assertEqual(
                overpayment.json()["error"]["code"],
                "payment_amount_exceeds_remaining",
            )

        self.assertEqual(self._payment_effects()["payments"], 0)

    def test_idempotent_replay_after_full_and_conflicting_reuse(self):
        key = "stable-client-reference"
        with self.client_as(103) as waiter:
            first = self._post_payment(
                waiter,
                amount="100.00",
                method="cash",
                reference="table-1",
                idempotency_key=key,
            )
            replay = self._post_payment(
                waiter,
                amount="100.00",
                method="cash",
                reference="table-1",
                idempotency_key=key,
            )
            self.assertEqual(first.status_code, 201, first.text)
            self.assertEqual(replay.status_code, 201, replay.text)
            self.assertEqual(
                replay.json()["payment_id"],
                first.json()["payment_id"],
            )
            self.assertTrue(replay.json()["is_idempotent_replay"])
            self.assertEqual(self._payment_effects()["payments"], 1)

            conflicts = (
                {"amount": "99.99"},
                {"method": "card"},
                {"reference": "different"},
                {"currency": "USD"},
            )
            for override in conflicts:
                with self.subTest(override=override):
                    payload = {
                        "amount": "100.00",
                        "method": "cash",
                        "currency": "EUR",
                        "reference": "table-1",
                        "idempotency_key": key,
                    }
                    payload.update(override)
                    response = waiter.post(
                        f"/api/dining/101/settlements/"
                        f"{self.settlement_ids[101]}/payments",
                        json=payload,
                    )
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(
                        response.json()["error"]["code"],
                        "payment_idempotency_conflict",
                    )
        self.assertEqual(self._payment_effects()["paid"], Decimal("100.00"))

    def test_database_idempotency_constraint_is_per_restaurant(self):
        with self.SessionTesting() as db:
            now = datetime.utcnow()
            first = Payment(
                restaurant_id=101,
                settlement_id=self.settlement_ids[101],
                status="completed",
                method="cash",
                amount=Decimal("1.00"),
                currency="EUR",
                idempotency_key="db-unique",
                created_by_user_id=101,
                paid_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(first)
            db.commit()
            duplicate = Payment(
                restaurant_id=101,
                settlement_id=self.settlement_ids[101],
                status="completed",
                method="card",
                amount=Decimal("1.00"),
                currency="EUR",
                idempotency_key="db-unique",
                created_by_user_id=101,
                paid_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(duplicate)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            cross_restaurant = Payment(
                restaurant_id=102,
                settlement_id=self.settlement_ids[102],
                status="completed",
                method="other",
                amount=Decimal("1.00"),
                currency="EUR",
                idempotency_key="db-unique",
                created_by_user_id=101,
                paid_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(cross_restaurant)
            db.commit()

    def test_settlement_lookup_status_and_tenant_isolation(self):
        with self.client_as(101) as owner:
            missing = self._balance(
                owner,
                settlement_id=999999,
            )
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(
                missing.json()["error"]["code"],
                "payment_settlement_not_found",
            )

            cross_tenant_id = self.settlement_ids[102]
            hidden = self._balance(
                owner,
                restaurant_id=101,
                settlement_id=cross_tenant_id,
            )
            self.assertEqual(hidden.status_code, 404)
            self.assertEqual(
                hidden.json()["error"]["code"],
                "payment_settlement_not_found",
            )

            allowed = self._balance(
                owner,
                restaurant_id=102,
                settlement_id=cross_tenant_id,
            )
            self.assertEqual(allowed.status_code, 200, allowed.text)

        with self.client_as(103) as waiter:
            denied = self._balance(
                waiter,
                restaurant_id=102,
                settlement_id=self.settlement_ids[102],
            )
            self.assertEqual(denied.status_code, 403)

        with self.assertRaises(AppError) as captured:
            _validate_settlement_status(
                SimpleNamespace(status="pending")
            )
        self.assertEqual(
            captured.exception.code,
            "payment_settlement_not_finalized",
        )

    def test_role_matrix_membership_revocation_and_active_switch(self):
        for user_id in (101, 102, 103):
            with self.subTest(user_id=user_id):
                with self.client_as(user_id) as client:
                    response = self._post_payment(
                        client,
                        amount="1.00",
                        idempotency_key=f"role-{user_id}",
                    )
                    self.assertEqual(
                        response.status_code,
                        201,
                        response.text,
                    )

        with self.client_as(105) as viewer:
            read = self._balance(viewer)
            write = self._post_payment(
                viewer,
                amount="1.00",
                idempotency_key="viewer-write",
            )
        self.assertEqual(read.status_code, 200)
        self.assertEqual(write.status_code, 403)

        with self.client_as(104) as cook:
            self.assertEqual(self._balance(cook).status_code, 403)
            self.assertEqual(
                self._post_payment(
                    cook,
                    amount="1.00",
                    idempotency_key="cook-write",
                ).status_code,
                403,
            )

        with self.client_as(
            101,
            active_restaurant_id=102,
        ) as multi_location_owner:
            switched = self._post_payment(
                multi_location_owner,
                amount="1.00",
                idempotency_key="active-switch",
            )
        self.assertEqual(switched.status_code, 201, switched.text)

        with self.SessionTesting() as db:
            membership = db.scalar(
                select(RestaurantMembership).where(
                    RestaurantMembership.user_id == 103,
                    RestaurantMembership.restaurant_id == 101,
                )
            )
            membership.is_active = False
            db.commit()
        with self.client_as(103) as revoked:
            self.assertEqual(self._balance(revoked).status_code, 403)

    def test_settlement_currency_is_frozen_from_restaurant_changes(self):
        with self.SessionTesting() as db:
            restaurant = db.get(Restaurant, 101)
            restaurant.currency = "USD"
            db.commit()
        with self.client_as(103) as waiter:
            response = self._post_payment(
                waiter,
                amount="1.00",
                currency=None,
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["currency"], "EUR")
        self.assertEqual(response.json()["balance"]["currency"], "EUR")

    def test_payment_does_not_mutate_operational_domains(self):
        before = self._payment_effects()
        with self.client_as(103) as waiter:
            response = self._post_payment(
                waiter,
                amount="25.00",
                method="card",
            )
        self.assertEqual(response.status_code, 201, response.text)
        after = self._payment_effects()
        self.assertEqual(after["payments"] - before["payments"], 1)
        self.assertEqual(after["paid"] - before["paid"], Decimal("25.00"))
        for key in (
            "settlement",
            "session",
            "open_sessions",
            "stock",
            "movements",
            "analytics",
            "fulfillments",
            "orders",
        ):
            self.assertEqual(after[key], before[key], key)

    def test_failure_after_flush_rolls_back_completely(self):
        before = self._payment_effects()
        with self.SessionTesting() as db:
            actor = db.get(User, 103)
            with patch.object(
                db,
                "commit",
                side_effect=RuntimeError("commit failure"),
            ):
                with self.assertRaises(AppError) as captured:
                    create_payment(
                        db,
                        actor,
                        101,
                        self.settlement_ids[101],
                        PaymentCreate(
                            amount="10.00",
                            method="cash",
                            currency="EUR",
                            idempotency_key="rollback-after-flush",
                        ),
                    )
        self.assertEqual(
            captured.exception.code,
            "payment_transaction_failed",
        )
        self.assertEqual(self._payment_effects(), before)

    def test_concurrent_partial_payments_cannot_overpay(self):
        barrier = threading.Barrier(2)

        def register(key: str):
            with self.SessionTesting() as db:
                actor = db.get(User, 103)
                barrier.wait(timeout=10)
                try:
                    result = create_payment(
                        db,
                        actor,
                        101,
                        self.settlement_ids[101],
                        PaymentCreate(
                            amount="60.00",
                            method="cash",
                            currency="EUR",
                            idempotency_key=key,
                        ),
                    )
                    return result.payment_id
                except AppError as exc:
                    return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    register,
                    ("concurrent-a", "concurrent-b"),
                )
            )
        self.assertEqual(
            sum(isinstance(result, int) for result in results),
            1,
            results,
        )
        self.assertIn("payment_amount_exceeds_remaining", results)
        effects = self._payment_effects()
        self.assertEqual(effects["payments"], 1)
        self.assertEqual(effects["paid"], Decimal("60.00"))

    def test_concurrent_same_key_returns_one_payment_and_replay(self):
        barrier = threading.Barrier(2)

        def register():
            with self.SessionTesting() as db:
                actor = db.get(User, 103)
                barrier.wait(timeout=10)
                result = create_payment(
                    db,
                    actor,
                    101,
                    self.settlement_ids[101],
                    PaymentCreate(
                        amount="100.00",
                        method="cash",
                        currency="EUR",
                        idempotency_key="concurrent-replay",
                    ),
                )
                return (
                    result.payment_id,
                    result.is_idempotent_replay,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: register(), range(2)))
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(
            sorted(result[1] for result in results),
            [False, True],
        )
        self.assertEqual(self._payment_effects()["payments"], 1)

    def test_multiple_settlements_remain_independent(self):
        with self.SessionTesting() as db:
            second = self._insert_settlement(
                db,
                restaurant_id=101,
                total=Decimal("20.00"),
            )
            second_id = second.id
            db.commit()
        with self.client_as(103) as waiter:
            first_payment = self._post_payment(
                waiter,
                amount="10.00",
                idempotency_key="first-settlement",
            )
            second_payment = self._post_payment(
                waiter,
                amount="20.00",
                settlement_id=second_id,
                idempotency_key="second-settlement",
            )
            first_balance = self._balance(waiter)
            second_balance = self._balance(
                waiter,
                settlement_id=second_id,
            )
        self.assertEqual(first_payment.status_code, 201)
        self.assertEqual(second_payment.status_code, 201)
        self.assertEqual(
            first_balance.json()["amount_remaining"],
            "90.00",
        )
        self.assertEqual(
            second_balance.json()["amount_remaining"],
            "0.00",
        )

    def test_frontend_and_openapi_expose_payment_foundation_only(self):
        project_root = Path(__file__).resolve().parents[1]
        template = (
            project_root / "app/templates/waiter/workspace.html"
        ).read_text(encoding="utf-8")
        javascript = (
            project_root / "app/static/js/waiter.js"
        ).read_text(encoding="utf-8")
        frontend = f"{template}\n{javascript}".lower()

        for text_value in (
            "registrar pago",
            "paymenttotal",
            "paymentpaid",
            "paymentremaining",
            "paymentidempotencykey",
        ):
            self.assertIn(text_value, frontend)
        for forbidden in (
            "procesar tarjeta",
            "cobrar con tpv",
            "emitir factura",
            "abrir caja",
        ):
            self.assertNotIn(forbidden, frontend)
        self.assertIn("withbusybutton(button", javascript.lower())
        self.assertIn(
            "state.paymentBalance = result.balance",
            javascript,
        )
        self.assertNotIn("parseFloat", javascript)

        openapi = app.openapi()
        base_path = (
            "/api/dining/{restaurant_id}/settlements/"
            "{settlement_id}"
        )
        self.assertIn(f"{base_path}/payments", openapi["paths"])
        self.assertIn(f"{base_path}/balance", openapi["paths"])
        operations = [
            operation["operationId"]
            for path in openapi["paths"].values()
            for method, operation in path.items()
            if method.lower()
            in {"get", "post", "put", "patch", "delete"}
        ]
        self.assertEqual(len(operations), len(set(operations)))
