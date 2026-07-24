import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    AnalyticsEvent,
    Category,
    Dish,
    DishIngredient,
    InventoryItem,
    InventoryMovement,
    KitchenTicket,
    KitchenTicketLine,
    Order,
    OrderFulfillment,
    OrderFulfillmentLine,
    OrderLine,
    Payment,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    ServiceSessionSettlement,
    ServiceSessionSettlementLine,
    ServiceSessionSettlementOrder,
    User,
    Zone,
)
from app.services.service_session_settlement_service import (
    _get_settlement as real_get_settlement,
)


class ServiceSessionSettlementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/settlement.db",
            connect_args={"check_same_thread": False},
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
                        id=1,
                        name="Centro",
                        slug="settlement-centro",
                        currency="EUR",
                    ),
                    Restaurant(
                        id=2,
                        name="Playa",
                        slug="settlement-playa",
                        currency="EUR",
                    ),
                ]
            )
            roles = ("owner", "manager", "waiter", "cook", "viewer", "owner")
            for user_id, role in enumerate(roles, start=1):
                restaurant_id = 1 if user_id < 6 else 2
                db.add(
                    User(
                        id=user_id,
                        email=f"settlement-{user_id}@hostai.test",
                        hashed_password="not-used",
                        full_name=f"Settlement {role.title()}",
                        role=role,
                        restaurant_id=restaurant_id,
                        is_active=True,
                        created_at=datetime.utcnow(),
                    )
                )
                db.add(
                    RestaurantMembership(
                        user_id=user_id,
                        restaurant_id=restaurant_id,
                        role=role,
                        is_active=True,
                        created_by_user_id=1 if restaurant_id == 1 else 6,
                    )
                )
            db.add(
                RestaurantMembership(
                    user_id=1,
                    restaurant_id=2,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                )
            )
            db.commit()

    def setUp(self):
        with self.SessionTesting() as db:
            db.execute(delete(Payment))
            db.execute(delete(ServiceSessionSettlementLine))
            db.execute(delete(ServiceSessionSettlementOrder))
            db.execute(delete(ServiceSessionSettlement))
            db.execute(delete(OrderFulfillmentLine))
            db.execute(delete(OrderFulfillment))
            db.execute(delete(KitchenTicketLine))
            db.execute(delete(KitchenTicket))
            db.execute(delete(OrderLine))
            db.execute(delete(Order))
            db.execute(delete(ServiceSession))
            db.execute(delete(RestaurantTable))
            db.execute(delete(Zone))
            db.execute(delete(DishIngredient))
            db.execute(delete(InventoryMovement))
            db.execute(delete(InventoryItem))
            db.execute(delete(AnalyticsEvent))
            db.execute(delete(Dish))
            db.execute(delete(Category))
            db.execute(
                RestaurantMembership.__table__.update().values(is_active=True)
            )
            db.execute(
                Restaurant.__table__.update().values(currency="EUR")
            )
            db.commit()

            self.zone_ids: dict[int, int] = {}
            self.table_ids: dict[int, int] = {}
            self.session_ids: dict[int, int] = {}
            self.dish_ids: dict[str, int] = {}
            self.inventory_ids: dict[str, int] = {}
            for restaurant_id in (1, 2):
                category = Category(
                    restaurant_id=restaurant_id,
                    name=f"Menu {restaurant_id}",
                )
                zone = Zone(
                    restaurant_id=restaurant_id,
                    name=f"Zone {restaurant_id}",
                )
                db.add_all([category, zone])
                db.flush()
                self.zone_ids[restaurant_id] = zone.id
                table = RestaurantTable(
                    restaurant_id=restaurant_id,
                    zone_id=zone.id,
                    code=f"M{restaurant_id}",
                    capacity=4,
                )
                db.add(table)
                db.flush()
                self.table_ids[restaurant_id] = table.id
                service_session = ServiceSession(
                    restaurant_id=restaurant_id,
                    table_id=table.id,
                    status="open",
                    opened_at=datetime.utcnow(),
                    guest_count=2,
                    opened_by_user_id=1 if restaurant_id == 1 else 6,
                )
                db.add(service_session)
                db.flush()
                self.session_ids[restaurant_id] = service_session.id

                dish = Dish(
                    restaurant_id=restaurant_id,
                    category_id=category.id,
                    name=f"Primary {restaurant_id}",
                    price=Decimal("0.10"),
                )
                inventory = InventoryItem(
                    restaurant_id=restaurant_id,
                    name=f"Ingredient {restaurant_id}",
                    unit="unit",
                    current_stock=100,
                    minimum_stock=0,
                    ideal_stock=100,
                    cost=3,
                )
                db.add_all([dish, inventory])
                db.flush()
                db.add(
                    DishIngredient(
                        restaurant_id=restaurant_id,
                        dish_id=dish.id,
                        inventory_item_id=inventory.id,
                        quantity=1,
                        unit="unit",
                    )
                )
                self.dish_ids[f"primary_{restaurant_id}"] = dish.id
                self.inventory_ids[f"primary_{restaurant_id}"] = inventory.id

            category_one = db.scalar(
                select(Category).where(Category.restaurant_id == 1)
            )
            second_dish = Dish(
                restaurant_id=1,
                category_id=category_one.id,
                name="Second",
                price=Decimal("0.20"),
            )
            second_inventory = InventoryItem(
                restaurant_id=1,
                name="Second ingredient",
                unit="unit",
                current_stock=100,
                minimum_stock=0,
                ideal_stock=100,
                cost=4,
            )
            db.add_all([second_dish, second_inventory])
            db.flush()
            db.add(
                DishIngredient(
                    restaurant_id=1,
                    dish_id=second_dish.id,
                    inventory_item_id=second_inventory.id,
                    quantity=1,
                    unit="unit",
                )
            )
            self.dish_ids["second_1"] = second_dish.id
            self.inventory_ids["second_1"] = second_inventory.id
            db.commit()

    @contextmanager
    def client_as(
        self,
        user_id: int,
        *,
        active_restaurant_id: int = 1,
    ):
        roles = {
            1: "owner",
            2: "manager",
            3: "waiter",
            4: "cook",
            5: "viewer",
            6: "owner",
        }
        user = User(
            id=user_id,
            email=f"settlement-{user_id}@hostai.test",
            hashed_password="not-used",
            full_name=f"Settlement {roles[user_id].title()}",
            role=roles[user_id],
            restaurant_id=active_restaurant_id,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_active_restaurant_id] = (
            lambda: active_restaurant_id
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_active_restaurant_id, None)

    def _new_session(
        self,
        *,
        restaurant_id: int = 1,
        opened_by_user_id: int | None = None,
    ) -> int:
        with self.SessionTesting() as db:
            table_count = db.scalar(
                select(func.count())
                .select_from(RestaurantTable)
                .where(RestaurantTable.restaurant_id == restaurant_id)
            )
            table = RestaurantTable(
                restaurant_id=restaurant_id,
                zone_id=self.zone_ids[restaurant_id],
                code=f"N{restaurant_id}-{table_count + 1}",
                capacity=4,
            )
            db.add(table)
            db.flush()
            service_session = ServiceSession(
                restaurant_id=restaurant_id,
                table_id=table.id,
                status="open",
                opened_at=datetime.utcnow(),
                guest_count=2,
                opened_by_user_id=(
                    opened_by_user_id
                    or (1 if restaurant_id == 1 else 6)
                ),
            )
            db.add(service_session)
            db.commit()
            return service_session.id

    def _create_order(
        self,
        client: TestClient,
        *,
        session_id: int | None = None,
        restaurant_id: int = 1,
        dish_ids: list[int] | None = None,
        submit: bool = True,
    ) -> dict:
        selected_session_id = (
            session_id or self.session_ids[restaurant_id]
        )
        response = client.post(
            f"/api/orders/{restaurant_id}/sessions/"
            f"{selected_session_id}",
            json={},
        )
        self.assertEqual(response.status_code, 201, response.text)
        order = response.json()
        selected_dishes = dish_ids or [
            self.dish_ids[f"primary_{restaurant_id}"]
        ]
        for dish_id in selected_dishes:
            response = client.post(
                f"/api/orders/{restaurant_id}/{order['id']}/lines",
                json={"dish_id": dish_id, "quantity": 1},
            )
            self.assertEqual(response.status_code, 200, response.text)
            order = response.json()
        if submit:
            response = client.post(
                f"/api/orders/{restaurant_id}/{order['id']}/submit"
            )
            self.assertEqual(response.status_code, 200, response.text)
            order = response.json()
        return order

    def _ticket(self, order_id: int) -> KitchenTicket:
        with self.SessionTesting() as db:
            return db.scalar(
                select(KitchenTicket).where(
                    KitchenTicket.order_id == order_id
                )
            )

    def _fulfill_order(
        self,
        order_id: int,
        *,
        actor_user_id: int = 3,
        restaurant_id: int = 1,
    ) -> dict:
        ticket = self._ticket(order_id)
        cook_id = 4 if restaurant_id == 1 else 6
        with self.client_as(
            cook_id,
            active_restaurant_id=restaurant_id,
        ) as cook:
            for action in ("start", "ready", "serve"):
                response = cook.post(
                    f"/api/kitchen/{restaurant_id}/tickets/"
                    f"{ticket.id}/{action}"
                )
                self.assertEqual(response.status_code, 200, response.text)
        with self.client_as(
            actor_user_id,
            active_restaurant_id=restaurant_id,
        ) as actor:
            response = actor.post(
                f"/api/orders/{restaurant_id}/{order_id}/fulfill"
            )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _effect_counts(self, restaurant_id: int = 1) -> dict[str, int]:
        with self.SessionTesting() as db:
            return {
                "settlements": db.scalar(
                    select(func.count())
                    .select_from(ServiceSessionSettlement)
                    .where(
                        ServiceSessionSettlement.restaurant_id
                        == restaurant_id
                    )
                ),
                "payments": db.scalar(
                    select(func.count())
                    .select_from(Payment)
                    .where(Payment.restaurant_id == restaurant_id)
                ),
                "settlement_orders": db.scalar(
                    select(func.count())
                    .select_from(ServiceSessionSettlementOrder)
                    .where(
                        ServiceSessionSettlementOrder.restaurant_id
                        == restaurant_id
                    )
                ),
                "settlement_lines": db.scalar(
                    select(func.count())
                    .select_from(ServiceSessionSettlementLine)
                    .where(
                        ServiceSessionSettlementLine.restaurant_id
                        == restaurant_id
                    )
                ),
                "movements": db.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                    .where(
                        InventoryMovement.restaurant_id == restaurant_id
                    )
                ),
                "analytics": db.scalar(
                    select(func.count())
                    .select_from(AnalyticsEvent)
                    .where(
                        AnalyticsEvent.restaurant_id == restaurant_id
                    )
                ),
                "fulfillments": db.scalar(
                    select(func.count())
                    .select_from(OrderFulfillment)
                    .where(
                        OrderFulfillment.restaurant_id == restaurant_id
                    )
                ),
            }

    def test_empty_draft_and_submitted_sessions_are_not_settleable(self):
        session_id = self.session_ids[1]
        with self.client_as(3) as waiter:
            empty = waiter.post(
                f"/api/dining/1/sessions/{session_id}/settle"
            )
            draft_order = self._create_order(
                waiter,
                session_id=session_id,
                submit=False,
            )
            draft = waiter.post(
                f"/api/dining/1/sessions/{session_id}/settle"
            )
            waiter.post(
                f"/api/orders/1/{draft_order['id']}/submit"
            )
            submitted = waiter.post(
                f"/api/dining/1/sessions/{session_id}/settle"
            )

        self.assertEqual(
            empty.json()["error"]["code"],
            "settlement_no_billable_orders",
        )
        self.assertEqual(
            draft.json()["error"]["code"],
            "settlement_orders_pending",
        )
        self.assertEqual(
            submitted.json()["error"]["code"],
            "settlement_orders_pending",
        )
        with self.SessionTesting() as db:
            service_session = db.get(ServiceSession, session_id)
        self.assertEqual(service_session.status, "open")
        self.assertEqual(self._effect_counts()["settlements"], 0)

    def test_completed_without_fulfillment_and_failed_fulfillment_block(self):
        with self.client_as(3) as waiter:
            completed = self._create_order(waiter, submit=False)
        with self.SessionTesting() as db:
            order = db.get(Order, completed["id"])
            order.status = "completed"
            order.completed_at = datetime.utcnow()
            db.commit()
        with self.client_as(3) as waiter:
            no_fulfillment = waiter.post(
                f"/api/dining/1/sessions/{self.session_ids[1]}/settle"
            )
        self.assertEqual(
            no_fulfillment.json()["error"]["code"],
            "settlement_fulfillment_required",
        )

        failed_session_id = self._new_session()
        with self.client_as(3) as waiter:
            failed_order = self._create_order(
                waiter,
                session_id=failed_session_id,
            )
        with self.SessionTesting() as db:
            db.add(
                OrderFulfillment(
                    restaurant_id=1,
                    order_id=failed_order["id"],
                    status="failed",
                    idempotency_key=(
                        f"order-fulfillment:1:{failed_order['id']}"
                    ),
                    attempt_count=1,
                    executed_by_user_id=3,
                    failed_at=datetime.utcnow(),
                    error_code="fulfillment_stock_insufficient",
                )
            )
            db.commit()
        with self.client_as(3) as waiter:
            failed_fulfillment = waiter.post(
                f"/api/dining/1/sessions/{failed_session_id}/settle"
            )
        self.assertEqual(
            failed_fulfillment.json()["error"]["code"],
            "settlement_fulfillment_required",
        )

    def test_single_order_settlement_freezes_and_replays_exact_snapshot(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
        self._fulfill_order(order["id"])
        before = self._effect_counts()

        with self.assertLogs(
            "app.service_session_settlement",
            level="INFO",
        ) as logs:
            with self.client_as(3) as waiter:
                first = waiter.post(
                    f"/api/dining/1/sessions/"
                    f"{self.session_ids[1]}/settle"
                )
        self.assertEqual(first.status_code, 200, first.text)
        payload = first.json()
        self.assertEqual(payload["status"], "finalized")
        self.assertEqual(payload["currency"], "EUR")
        self.assertEqual(payload["subtotal"], "0.10")
        self.assertEqual(payload["total"], "0.10")
        self.assertFalse(payload["is_idempotent_replay"])
        self.assertEqual(payload["orders"][0]["frozen_total"], "0.10")
        self.assertEqual(
            payload["orders"][0]["lines"][0]["unit_price"],
            "0.10",
        )
        self.assertTrue(
            any(
                f"service_session_id={self.session_ids[1]}" in entry
                for entry in logs.output
            )
        )

        after = self._effect_counts()
        self.assertEqual(after["settlements"] - before["settlements"], 1)
        self.assertEqual(
            after["settlement_orders"] - before["settlement_orders"],
            1,
        )
        self.assertEqual(
            after["settlement_lines"] - before["settlement_lines"],
            1,
        )
        for key in ("movements", "analytics", "fulfillments"):
            self.assertEqual(after[key], before[key])

        with self.SessionTesting() as db:
            stored_order = db.get(Order, order["id"])
            order_line = db.get(OrderLine, order["lines"][0]["id"])
            dish = db.get(Dish, order_line.dish_id)
            restaurant = db.get(Restaurant, 1)
            service_session = db.get(
                ServiceSession,
                self.session_ids[1],
            )
            open_sessions = db.scalar(
                select(func.count())
                .select_from(ServiceSession)
                .where(
                    ServiceSession.table_id == service_session.table_id,
                    ServiceSession.status == "open",
                )
            )
            self.assertEqual(stored_order.status, "completed")
            self.assertEqual(service_session.status, "closed")
            self.assertIsNotNone(service_session.closed_at)
            self.assertEqual(service_session.closed_by_user_id, 3)
            self.assertEqual(open_sessions, 0)
            order_line.unit_price = Decimal("9.99")
            order_line.dish_name = "Changed order line"
            dish.price = Decimal("8.88")
            dish.name = "Changed dish"
            restaurant.currency = "USD"
            db.commit()

        calls = 0

        def settlement_race_get(db, restaurant_id, session_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            return real_get_settlement(db, restaurant_id, session_id)

        with patch(
            "app.services.service_session_settlement_service."
            "_get_settlement",
            side_effect=settlement_race_get,
        ):
            with self.client_as(3) as waiter:
                replay = waiter.post(
                    f"/api/dining/1/sessions/"
                    f"{self.session_ids[1]}/settle"
                )
        self.assertEqual(replay.status_code, 200, replay.text)
        replay_payload = replay.json()
        self.assertTrue(replay_payload["is_idempotent_replay"])
        self.assertEqual(
            replay_payload["settlement_id"],
            payload["settlement_id"],
        )
        self.assertEqual(replay_payload["total"], "0.10")
        self.assertEqual(replay_payload["currency"], "EUR")
        self.assertEqual(
            replay_payload["orders"][0]["lines"][0]["dish_name"],
            "Primary 1",
        )
        self.assertEqual(
            replay_payload["orders"][0]["lines"][0]["unit_price"],
            "0.10",
        )
        self.assertEqual(self._effect_counts(), after)

        with self.client_as(3) as waiter:
            room = waiter.get("/api/dining/1/room")
            rejected_order = waiter.post(
                f"/api/orders/1/sessions/{self.session_ids[1]}",
                json={},
            )
            reopened = waiter.post(
                f"/api/dining/1/tables/{self.table_ids[1]}/sessions",
                json={"guest_count": 2},
            )
        self.assertEqual(room.json()["free_tables"], 1)
        self.assertEqual(room.json()["occupied_tables"], 0)
        self.assertEqual(rejected_order.status_code, 409)
        self.assertEqual(
            rejected_order.json()["error"]["code"],
            "service_session_not_open",
        )
        self.assertEqual(reopened.status_code, 201, reopened.text)

    def test_multiple_orders_decimal_sum_and_cancelled_exclusion(self):
        session_id = self.session_ids[1]
        with self.client_as(3) as waiter:
            first = self._create_order(
                waiter,
                session_id=session_id,
                dish_ids=[self.dish_ids["primary_1"]],
            )
            second = self._create_order(
                waiter,
                session_id=session_id,
                dish_ids=[self.dish_ids["second_1"]],
            )
            cancelled = self._create_order(
                waiter,
                session_id=session_id,
                submit=False,
            )
            waiter.post(
                f"/api/orders/1/{cancelled['id']}/cancel"
            )
        self._fulfill_order(first["id"])
        self._fulfill_order(second["id"])
        with self.client_as(3) as waiter:
            response = waiter.post(
                f"/api/dining/1/sessions/{session_id}/settle"
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["subtotal"], "0.30")
        self.assertEqual(payload["total"], "0.30")
        self.assertEqual(len(payload["orders"]), 2)
        self.assertEqual(
            {item["order_id"] for item in payload["orders"]},
            {first["id"], second["id"]},
        )
        self.assertNotIn(
            cancelled["id"],
            {item["order_id"] for item in payload["orders"]},
        )

    def test_cancelled_kitchen_line_is_not_included_in_settlement(self):
        with self.client_as(3) as waiter:
            order = self._create_order(
                waiter,
                dish_ids=[
                    self.dish_ids["primary_1"],
                    self.dish_ids["second_1"],
                ],
            )
        ticket = self._ticket(order["id"])
        with self.SessionTesting() as db:
            line_ids = list(
                db.scalars(
                    select(KitchenTicketLine.id)
                    .where(
                        KitchenTicketLine.kitchen_ticket_id
                        == ticket.id
                    )
                    .order_by(KitchenTicketLine.id)
                )
            )
        with self.client_as(4) as cook:
            cook.post(f"/api/kitchen/1/tickets/{ticket.id}/start")
            cook.post(
                f"/api/kitchen/1/tickets/{ticket.id}/lines/"
                f"{line_ids[1]}/cancel"
            )
            cook.post(f"/api/kitchen/1/tickets/{ticket.id}/ready")
            cook.post(f"/api/kitchen/1/tickets/{ticket.id}/serve")
        with self.client_as(3) as waiter:
            waiter.post(f"/api/orders/1/{order['id']}/fulfill")
            response = waiter.post(
                f"/api/dining/1/sessions/{self.session_ids[1]}/settle"
            )

        self.assertEqual(response.status_code, 200, response.text)
        settlement_order = response.json()["orders"][0]
        self.assertEqual(settlement_order["frozen_total"], "0.10")
        self.assertEqual(settlement_order["included_line_count"], 1)
        self.assertEqual(len(settlement_order["lines"]), 1)
        self.assertEqual(
            settlement_order["lines"][0]["order_line_id"],
            order["lines"][0]["id"],
        )

    def test_direct_close_cannot_bypass_settlement(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
        self._fulfill_order(order["id"])
        with self.client_as(3) as waiter:
            response = waiter.post(
                f"/api/dining/1/sessions/{self.session_ids[1]}/close"
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"]["code"],
            "service_session_settlement_required",
        )
        with self.SessionTesting() as db:
            service_session = db.get(
                ServiceSession,
                self.session_ids[1],
            )
        self.assertEqual(service_session.status, "open")

    def test_closed_session_and_invalid_currency_are_rejected(self):
        empty_session = self.session_ids[1]
        with self.client_as(3) as waiter:
            waiter.post(
                f"/api/dining/1/sessions/{empty_session}/close"
            )
            closed = waiter.post(
                f"/api/dining/1/sessions/{empty_session}/settle"
            )
        self.assertEqual(closed.status_code, 409)
        self.assertEqual(
            closed.json()["error"]["code"],
            "settlement_session_not_open",
        )

        invalid_session = self._new_session()
        with self.client_as(3) as waiter:
            order = self._create_order(
                waiter,
                session_id=invalid_session,
            )
        self._fulfill_order(order["id"])
        with self.SessionTesting() as db:
            db.get(Restaurant, 1).currency = ""
            db.commit()
        with self.client_as(3) as waiter:
            invalid = waiter.post(
                f"/api/dining/1/sessions/{invalid_session}/settle"
            )
        self.assertEqual(invalid.status_code, 409)
        self.assertEqual(
            invalid.json()["error"]["code"],
            "settlement_currency_mismatch",
        )
        with self.SessionTesting() as db:
            service_session = db.get(ServiceSession, invalid_session)
        self.assertEqual(service_session.status, "open")

    def test_roles_for_create_and_read_are_centralized(self):
        settled: list[tuple[int, int]] = []
        for user_id in (1, 2, 3):
            with self.subTest(user_id=user_id):
                session_id = (
                    self.session_ids[1]
                    if not settled
                    else self._new_session(opened_by_user_id=user_id)
                )
                with self.client_as(user_id) as actor:
                    order = self._create_order(
                        actor,
                        session_id=session_id,
                    )
                self._fulfill_order(
                    order["id"],
                    actor_user_id=user_id,
                )
                with self.client_as(user_id) as actor:
                    response = actor.post(
                        f"/api/dining/1/sessions/{session_id}/settle"
                    )
                self.assertEqual(response.status_code, 200, response.text)
                settled.append((session_id, response.json()["settlement_id"]))

        restricted_session = self._new_session()
        with self.client_as(3) as waiter:
            restricted_order = self._create_order(
                waiter,
                session_id=restricted_session,
            )
        self._fulfill_order(restricted_order["id"])
        for user_id in (4, 5):
            with self.subTest(rejected_user_id=user_id):
                with self.client_as(user_id) as actor:
                    response = actor.post(
                        f"/api/dining/1/sessions/"
                        f"{restricted_session}/settle"
                    )
                self.assertEqual(response.status_code, 403, response.text)
        with self.client_as(1) as owner:
            owner.post(
                f"/api/dining/1/sessions/{restricted_session}/settle"
            )
        with self.client_as(5) as viewer:
            viewer_read = viewer.get(
                f"/api/dining/1/sessions/"
                f"{restricted_session}/settlement"
            )
        with self.client_as(4) as cook:
            cook_read = cook.get(
                f"/api/dining/1/sessions/"
                f"{restricted_session}/settlement"
            )
        self.assertEqual(viewer_read.status_code, 200, viewer_read.text)
        self.assertEqual(cook_read.status_code, 403, cook_read.text)

    def test_idor_revocation_and_active_restaurant_switch(self):
        with self.client_as(6, active_restaurant_id=2) as owner_two:
            order_two = self._create_order(
                owner_two,
                restaurant_id=2,
            )
        self._fulfill_order(
            order_two["id"],
            actor_user_id=6,
            restaurant_id=2,
        )
        with self.client_as(3) as waiter:
            idor = waiter.post(
                f"/api/dining/2/sessions/{self.session_ids[2]}/settle"
            )
        self.assertEqual(idor.status_code, 403)
        self.assertEqual(
            idor.json()["error"]["code"],
            "restaurant_access_denied",
        )
        with self.client_as(1, active_restaurant_id=2) as multi_owner:
            allowed = multi_owner.post(
                f"/api/dining/2/sessions/{self.session_ids[2]}/settle"
            )
        self.assertEqual(allowed.status_code, 200, allowed.text)

        with self.client_as(3) as waiter:
            order_one = self._create_order(waiter)
        self._fulfill_order(order_one["id"])
        with self.SessionTesting() as db:
            membership = db.scalar(
                select(RestaurantMembership).where(
                    RestaurantMembership.user_id == 3,
                    RestaurantMembership.restaurant_id == 1,
                )
            )
            membership.is_active = False
            db.commit()
        with self.client_as(3) as waiter:
            revoked = waiter.post(
                f"/api/dining/1/sessions/{self.session_ids[1]}/settle"
            )
        self.assertEqual(revoked.status_code, 403)
        self.assertEqual(
            revoked.json()["error"]["code"],
            "restaurant_access_denied",
        )

    def test_calculation_failure_rolls_back_everything(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
        self._fulfill_order(order["id"])
        before = self._effect_counts()
        with patch(
            "app.services.service_session_settlement_service."
            "_build_order_snapshot",
            side_effect=RuntimeError("calculation failed"),
        ):
            with self.client_as(3) as waiter:
                response = waiter.post(
                    f"/api/dining/1/sessions/"
                    f"{self.session_ids[1]}/settle"
                )
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(
            response.json()["error"]["code"],
            "settlement_transaction_failed",
        )
        self._assert_failed_settlement_effects(before, order["id"])

    def test_relation_failure_rolls_back_everything(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
        self._fulfill_order(order["id"])
        before = self._effect_counts()
        with patch(
            "app.services.service_session_settlement_service."
            "ServiceSessionSettlementLine",
            side_effect=RuntimeError("relation failed"),
        ):
            with self.client_as(3) as waiter:
                response = waiter.post(
                    f"/api/dining/1/sessions/"
                    f"{self.session_ids[1]}/settle"
                )
        self.assertEqual(response.status_code, 500, response.text)
        self._assert_failed_settlement_effects(before, order["id"])

    def test_session_close_failure_rolls_back_everything(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
        self._fulfill_order(order["id"])
        before = self._effect_counts()
        with patch(
            "app.services.service_session_settlement_service."
            "_close_session_record",
            side_effect=RuntimeError("close failed"),
        ):
            with self.client_as(3) as waiter:
                response = waiter.post(
                    f"/api/dining/1/sessions/"
                    f"{self.session_ids[1]}/settle"
                )
        self.assertEqual(response.status_code, 500, response.text)
        self._assert_failed_settlement_effects(before, order["id"])

    def _assert_failed_settlement_effects(
        self,
        before: dict[str, int],
        order_id: int,
    ) -> None:
        self.assertEqual(self._effect_counts(), before)
        with self.SessionTesting() as db:
            service_session = db.get(
                ServiceSession,
                self.session_ids[1],
            )
            order = db.get(Order, order_id)
            open_sessions = db.scalar(
                select(func.count())
                .select_from(ServiceSession)
                .where(
                    ServiceSession.table_id == service_session.table_id,
                    ServiceSession.status == "open",
                )
            )
        self.assertEqual(service_session.status, "open")
        self.assertIsNone(service_session.closed_at)
        self.assertIsNone(service_session.closed_by_user_id)
        self.assertEqual(open_sessions, 1)
        self.assertEqual(order.status, "completed")

    def test_database_guarantees_one_settlement_without_creating_payments(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
        self._fulfill_order(order["id"])
        with self.client_as(3) as waiter:
            response = waiter.post(
                f"/api/dining/1/sessions/{self.session_ids[1]}/settle"
            )
        self.assertEqual(response.status_code, 200, response.text)
        with self.SessionTesting() as db:
            existing = db.scalar(select(ServiceSessionSettlement))
            duplicate = ServiceSessionSettlement(
                restaurant_id=1,
                service_session_id=self.session_ids[1],
                status="finalized",
                idempotency_key=existing.idempotency_key,
                currency="EUR",
                subtotal=Decimal("0.10"),
                total=Decimal("0.10"),
                created_by_user_id=3,
                finalized_at=datetime.utcnow(),
            )
            db.add(duplicate)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

        self.assertIn("payments", Base.metadata.tables)
        self.assertEqual(self._effect_counts()["settlements"], 1)
        self.assertEqual(self._effect_counts()["payments"], 0)

    def test_multiple_sessions_settle_independently(self):
        second_session = self._new_session()
        with self.client_as(3) as waiter:
            first_order = self._create_order(waiter)
            second_order = self._create_order(
                waiter,
                session_id=second_session,
            )
        self._fulfill_order(first_order["id"])
        self._fulfill_order(second_order["id"])
        with self.client_as(3) as waiter:
            first = waiter.post(
                f"/api/dining/1/sessions/{self.session_ids[1]}/settle"
            )
            second = waiter.post(
                f"/api/dining/1/sessions/{second_session}/settle"
            )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertNotEqual(
            first.json()["settlement_id"],
            second.json()["settlement_id"],
        )
        self.assertEqual(self._effect_counts()["settlements"], 2)

    def test_frontend_and_openapi_keep_explicit_settlement_action(self):
        project_root = Path(__file__).resolve().parents[1]
        script = (
            project_root / "app/static/js/waiter.js"
        ).read_text(encoding="utf-8")
        template = (
            project_root / "app/templates/waiter/workspace.html"
        ).read_text(encoding="utf-8")

        self.assertIn('id="settleSessionButton"', template)
        self.assertIn("Cerrar cuenta", template)
        self.assertIn("fulfillment_status === \"completed\"", script)
        self.assertIn("/settle`", script)
        self.assertEqual(script.count("/settle`"), 1)
        self.assertIn("withBusyButton(event.currentTarget", script)
        self.assertIn("settleSessionButton.hidden = !canSettle", script)
        frontend_text = (template + script).lower()
        self.assertNotIn("cobrar", frontend_text)

        schema = app.openapi()
        settle_path = (
            "/api/dining/{restaurant_id}/sessions/"
            "{session_id}/settle"
        )
        get_path = (
            "/api/dining/{restaurant_id}/sessions/"
            "{session_id}/settlement"
        )
        self.assertIn(settle_path, schema["paths"])
        self.assertIn(get_path, schema["paths"])
        operation_ids = [
            operation["operationId"]
            for path in schema["paths"].values()
            for operation in path.values()
            if (
                isinstance(operation, dict)
                and "operationId" in operation
            )
        ]
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
