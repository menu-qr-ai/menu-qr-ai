import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
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
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    User,
    Zone,
)
from app.services.operational_transaction_service import (
    process_sale_transaction as real_process_sale_transaction,
)


class OrderFulfillmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/fulfillment.db",
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
                    Restaurant(id=1, name="Centro", slug="fulfillment-centro"),
                    Restaurant(id=2, name="Playa", slug="fulfillment-playa"),
                ]
            )
            roles = ("owner", "manager", "waiter", "cook", "viewer", "owner")
            for user_id, role in enumerate(roles, start=1):
                restaurant_id = 1 if user_id < 6 else 2
                db.add(
                    User(
                        id=user_id,
                        email=f"fulfillment-{user_id}@hostai.test",
                        hashed_password="not-used",
                        full_name=f"Fulfillment {role.title()}",
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
            db.commit()

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
                table = RestaurantTable(
                    restaurant_id=restaurant_id,
                    zone_id=zone.id,
                    code=f"M{restaurant_id}",
                    capacity=4,
                )
                db.add(table)
                db.flush()
                session = ServiceSession(
                    restaurant_id=restaurant_id,
                    table_id=table.id,
                    status="open",
                    opened_at=datetime.utcnow(),
                    guest_count=2,
                    opened_by_user_id=1 if restaurant_id == 1 else 6,
                )
                db.add(session)
                db.flush()
                self.session_ids[restaurant_id] = session.id

                dish = Dish(
                    restaurant_id=restaurant_id,
                    category_id=category.id,
                    name=f"Dish {restaurant_id}",
                    price=Decimal("12.34"),
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
                        quantity=2,
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
                name="Second dish",
                price=Decimal("7.89"),
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
            no_recipe_dish = Dish(
                restaurant_id=1,
                category_id=category_one.id,
                name="No recipe",
                price=Decimal("5.50"),
            )
            db.add_all([second_dish, second_inventory, no_recipe_dish])
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
            self.dish_ids["no_recipe_1"] = no_recipe_dish.id
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
            email=f"fulfillment-{user_id}@hostai.test",
            hashed_password="not-used",
            full_name=f"Fulfillment {roles[user_id].title()}",
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

    def _create_order(
        self,
        client: TestClient,
        *,
        restaurant_id: int = 1,
        dish_ids: list[int] | None = None,
        quantities: list[int] | None = None,
        submit: bool = True,
    ) -> dict:
        response = client.post(
            f"/api/orders/{restaurant_id}/sessions/"
            f"{self.session_ids[restaurant_id]}",
            json={},
        )
        self.assertEqual(response.status_code, 201, response.text)
        order = response.json()
        selected_dishes = dish_ids or [
            self.dish_ids[f"primary_{restaurant_id}"]
        ]
        selected_quantities = quantities or [1] * len(selected_dishes)
        for dish_id, quantity in zip(
            selected_dishes,
            selected_quantities,
            strict=True,
        ):
            response = client.post(
                f"/api/orders/{restaurant_id}/{order['id']}/lines",
                json={"dish_id": dish_id, "quantity": quantity},
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
                select(KitchenTicket)
                .where(KitchenTicket.order_id == order_id)
            )

    def _advance_kitchen(
        self,
        order_id: int,
        target: str,
        *,
        restaurant_id: int = 1,
    ) -> dict:
        ticket = self._ticket(order_id)
        cook_user_id = 4 if restaurant_id == 1 else 6
        with self.client_as(
            cook_user_id,
            active_restaurant_id=restaurant_id,
        ) as cook:
            latest = None
            if target in {"preparing", "ready", "served"}:
                latest = cook.post(
                    f"/api/kitchen/{restaurant_id}/tickets/"
                    f"{ticket.id}/start"
                )
                self.assertEqual(latest.status_code, 200, latest.text)
            if target in {"ready", "served"}:
                latest = cook.post(
                    f"/api/kitchen/{restaurant_id}/tickets/"
                    f"{ticket.id}/ready"
                )
                self.assertEqual(latest.status_code, 200, latest.text)
            if target == "served":
                latest = cook.post(
                    f"/api/kitchen/{restaurant_id}/tickets/"
                    f"{ticket.id}/serve"
                )
                self.assertEqual(latest.status_code, 200, latest.text)
        return latest.json() if latest is not None else {}

    def _effect_counts(self, restaurant_id: int = 1) -> dict[str, int]:
        with self.SessionTesting() as db:
            return {
                "movements": db.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                    .where(
                        InventoryMovement.restaurant_id == restaurant_id,
                        InventoryMovement.movement_type == "OUT",
                    )
                ),
                "analytics": db.scalar(
                    select(func.count())
                    .select_from(AnalyticsEvent)
                    .where(
                        AnalyticsEvent.restaurant_id == restaurant_id,
                        AnalyticsEvent.event_type == "sale_processed",
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

    def test_draft_and_unserved_kitchen_states_are_rejected(self):
        with self.client_as(3) as waiter:
            draft = self._create_order(waiter, submit=False)
            response = waiter.post(
                f"/api/orders/1/{draft['id']}/fulfill"
            )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json()["error"]["code"],
                "order_not_fulfillable",
            )

            submitted = waiter.post(
                f"/api/orders/1/{draft['id']}/submit"
            ).json()
            self.assertEqual(submitted["status"], "submitted")
            response = waiter.post(
                f"/api/orders/1/{draft['id']}/fulfill"
            )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json()["error"]["code"],
                "kitchen_not_served",
            )

        for expected_state in ("preparing", "ready"):
            self._advance_kitchen(draft["id"], expected_state)
            with self.client_as(3) as waiter:
                response = waiter.post(
                    f"/api/orders/1/{draft['id']}/fulfill"
                )
                self.assertEqual(response.status_code, 409)
                self.assertEqual(
                    response.json()["error"]["code"],
                    "kitchen_not_served",
                )

        self.assertEqual(self._effect_counts()["fulfillments"], 0)

    def test_success_is_atomic_auditable_and_idempotent(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter, quantities=[2])
        self._advance_kitchen(order["id"], "served")
        with self.SessionTesting() as db:
            dish = db.get(Dish, order["lines"][0]["dish_id"])
            dish.price = Decimal("99.99")
            db.commit()

        before = self._effect_counts()
        with self.assertLogs("app.order_fulfillment", level="INFO") as logs:
            with self.client_as(3) as waiter:
                first = waiter.post(
                    f"/api/orders/1/{order['id']}/fulfill"
                )
                replay = waiter.post(
                    f"/api/orders/1/{order['id']}/fulfill"
                )
                lookup = waiter.get(
                    f"/api/orders/1/{order['id']}/fulfillment"
                )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(replay.status_code, 200, replay.text)
        payload = first.json()
        replay_payload = replay.json()
        self.assertEqual(payload["status"], "completed")
        self.assertFalse(payload["is_idempotent_replay"])
        self.assertTrue(replay_payload["is_idempotent_replay"])
        self.assertEqual(
            replay_payload["fulfillment_id"],
            payload["fulfillment_id"],
        )
        self.assertEqual(payload["processed_lines"][0]["unit_price"], "12.34")
        self.assertEqual(lookup.json()["fulfillment_id"], payload["fulfillment_id"])
        self.assertTrue(
            any(f"order_id={order['id']}" in entry for entry in logs.output)
        )

        after = self._effect_counts()
        self.assertEqual(after["movements"] - before["movements"], 1)
        self.assertEqual(after["analytics"] - before["analytics"], 1)
        self.assertEqual(after["fulfillments"] - before["fulfillments"], 1)
        with self.SessionTesting() as db:
            stored_order = db.get(Order, order["id"])
            service_session = db.get(
                ServiceSession,
                stored_order.service_session_id,
            )
            inventory = db.get(
                InventoryItem,
                self.inventory_ids["primary_1"],
            )
            movement = db.scalar(
                select(InventoryMovement).where(
                    InventoryMovement.origin_id
                    == payload["processed_lines"][0][
                        "operational_reference"
                    ]
                )
            )
            event = db.get(
                AnalyticsEvent,
                payload["processed_lines"][0]["analytics_event_id"],
            )
            fulfillment_count = db.scalar(
                select(func.count())
                .select_from(OrderFulfillment)
                .where(OrderFulfillment.order_id == order["id"])
            )
        self.assertEqual(stored_order.status, "completed")
        self.assertEqual(service_session.status, "open")
        self.assertEqual(inventory.current_stock, 96)
        self.assertEqual(fulfillment_count, 1)
        self.assertIsNotNone(movement)
        self.assertEqual(
            json.loads(event.metadata_json)["reference"],
            payload["processed_lines"][0]["operational_reference"],
        )

    def test_served_and_cancelled_mix_processes_only_served_lines(self):
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
                    .where(KitchenTicketLine.kitchen_ticket_id == ticket.id)
                    .order_by(KitchenTicketLine.id)
                )
            )
        with self.client_as(4) as cook:
            cook.post(f"/api/kitchen/1/tickets/{ticket.id}/start")
            cancelled = cook.post(
                f"/api/kitchen/1/tickets/{ticket.id}/lines/"
                f"{line_ids[1]}/cancel"
            )
            self.assertEqual(cancelled.status_code, 200, cancelled.text)
            cook.post(f"/api/kitchen/1/tickets/{ticket.id}/ready")
            served = cook.post(f"/api/kitchen/1/tickets/{ticket.id}/serve")
            self.assertEqual(served.json()["status"], "served")
        with self.client_as(3) as waiter:
            response = waiter.post(
                f"/api/orders/1/{order['id']}/fulfill"
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["processed_lines"]), 1)
        self.assertEqual(len(payload["skipped_lines"]), 1)
        self.assertEqual(payload["skipped_lines"][0]["movement_ids"], [])
        with self.SessionTesting() as db:
            primary = db.get(
                InventoryItem,
                self.inventory_ids["primary_1"],
            )
            second = db.get(
                InventoryItem,
                self.inventory_ids["second_1"],
            )
        self.assertEqual(primary.current_stock, 98)
        self.assertEqual(second.current_stock, 100)
        self.assertEqual(self._effect_counts()["analytics"], 1)

    def test_no_served_lines_is_rejected_even_if_ticket_is_inconsistent(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
        with self.SessionTesting() as db:
            ticket = db.scalar(
                select(KitchenTicket).where(
                    KitchenTicket.order_id == order["id"]
                )
            )
            ticket.status = "served"
            ticket.served_at = datetime.utcnow()
            for line in ticket.lines:
                line.status = "cancelled"
                line.cancelled_at = datetime.utcnow()
            db.commit()
        with self.client_as(3) as waiter:
            response = waiter.post(
                f"/api/orders/1/{order['id']}/fulfill"
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"]["code"],
            "fulfillment_no_served_lines",
        )
        self.assertEqual(self._effect_counts()["movements"], 0)

    def test_stock_failure_rolls_back_and_can_be_retried(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter, quantities=[2])
        self._advance_kitchen(order["id"], "served")
        with self.SessionTesting() as db:
            inventory = db.get(
                InventoryItem,
                self.inventory_ids["primary_1"],
            )
            inventory.current_stock = 1
            db.commit()
        with self.client_as(3) as waiter:
            failed = waiter.post(
                f"/api/orders/1/{order['id']}/fulfill"
            )

        self.assertEqual(failed.status_code, 409, failed.text)
        self.assertEqual(
            failed.json()["error"]["code"],
            "fulfillment_stock_insufficient",
        )
        self.assertEqual(self._effect_counts()["movements"], 0)
        self.assertEqual(self._effect_counts()["analytics"], 0)
        with self.SessionTesting() as db:
            fulfillment = db.scalar(
                select(OrderFulfillment).where(
                    OrderFulfillment.order_id == order["id"]
                )
            )
            stored_order = db.get(Order, order["id"])
            inventory = db.get(
                InventoryItem,
                self.inventory_ids["primary_1"],
            )
            self.assertEqual(fulfillment.status, "failed")
            self.assertEqual(fulfillment.attempt_count, 1)
            self.assertEqual(stored_order.status, "submitted")
            self.assertEqual(inventory.current_stock, 1)
            inventory.current_stock = 10
            db.commit()

        with self.client_as(2) as manager:
            retried = manager.post(
                f"/api/orders/1/{order['id']}/fulfill"
            )
        self.assertEqual(retried.status_code, 200, retried.text)
        with self.SessionTesting() as db:
            fulfillment = db.scalar(
                select(OrderFulfillment).where(
                    OrderFulfillment.order_id == order["id"]
                )
            )
        self.assertEqual(fulfillment.status, "completed")
        self.assertEqual(fulfillment.attempt_count, 2)

    def test_missing_cost_and_recipe_return_stable_errors(self):
        with self.SessionTesting() as db:
            inventory = db.get(
                InventoryItem,
                self.inventory_ids["primary_1"],
            )
            inventory.cost = None
            db.commit()
        with self.client_as(3) as waiter:
            cost_order = self._create_order(waiter)
        self._advance_kitchen(cost_order["id"], "served")
        with self.client_as(3) as waiter:
            cost_error = waiter.post(
                f"/api/orders/1/{cost_order['id']}/fulfill"
            )
            recipe_order = self._create_order(
                waiter,
                dish_ids=[self.dish_ids["no_recipe_1"]],
            )
        self._advance_kitchen(recipe_order["id"], "served")
        with self.client_as(3) as waiter:
            recipe_error = waiter.post(
                f"/api/orders/1/{recipe_order['id']}/fulfill"
            )

        self.assertEqual(
            cost_error.json()["error"]["code"],
            "fulfillment_cost_missing",
        )
        self.assertEqual(
            recipe_error.json()["error"]["code"],
            "fulfillment_recipe_missing",
        )
        self.assertEqual(self._effect_counts()["movements"], 0)
        self.assertEqual(self._effect_counts()["analytics"], 0)

    def test_middle_line_failure_rolls_back_every_effect(self):
        with self.client_as(3) as waiter:
            order = self._create_order(
                waiter,
                dish_ids=[
                    self.dish_ids["primary_1"],
                    self.dish_ids["second_1"],
                ],
            )
        self._advance_kitchen(order["id"], "served")
        calls = 0

        def fail_second(db, payload):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("second line failed")
            return real_process_sale_transaction(db, payload)

        with patch(
            "app.services.order_fulfillment_service."
            "process_sale_transaction",
            side_effect=fail_second,
        ):
            with self.client_as(3) as waiter:
                response = waiter.post(
                    f"/api/orders/1/{order['id']}/fulfill"
                )

        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(
            response.json()["error"]["code"],
            "fulfillment_transaction_failed",
        )
        self.assertEqual(self._effect_counts()["movements"], 0)
        self.assertEqual(self._effect_counts()["analytics"], 0)
        with self.SessionTesting() as db:
            stocks = list(
                db.scalars(
                    select(InventoryItem.current_stock)
                    .where(InventoryItem.restaurant_id == 1)
                    .order_by(InventoryItem.id)
                )
            )
            stored_order = db.get(Order, order["id"])
            line_count = db.scalar(
                select(func.count())
                .select_from(OrderFulfillmentLine)
            )
        self.assertEqual(stocks[:2], [100, 100])
        self.assertEqual(stored_order.status, "submitted")
        self.assertEqual(line_count, 0)

    def test_execute_permissions_and_viewer_read_access(self):
        for user_id in (1, 2, 3):
            with self.subTest(user_id=user_id):
                with self.client_as(user_id) as actor:
                    order = self._create_order(actor)
                self._advance_kitchen(order["id"], "served")
                with self.client_as(user_id) as actor:
                    response = actor.post(
                        f"/api/orders/1/{order['id']}/fulfill"
                    )
                self.assertEqual(response.status_code, 200, response.text)

        with self.client_as(3) as waiter:
            restricted_order = self._create_order(waiter)
        self._advance_kitchen(restricted_order["id"], "served")
        for user_id in (4, 5):
            with self.subTest(rejected_user_id=user_id):
                with self.client_as(user_id) as actor:
                    response = actor.post(
                        f"/api/orders/1/{restricted_order['id']}/fulfill"
                    )
                self.assertEqual(response.status_code, 403, response.text)
        with self.client_as(1) as owner:
            owner.post(
                f"/api/orders/1/{restricted_order['id']}/fulfill"
            )
        with self.client_as(5) as viewer:
            lookup = viewer.get(
                f"/api/orders/1/{restricted_order['id']}/fulfillment"
            )
        self.assertEqual(lookup.status_code, 200, lookup.text)

    def test_idor_revocation_and_active_restaurant_context(self):
        with self.client_as(6, active_restaurant_id=2) as owner_two:
            other_order = self._create_order(
                owner_two,
                restaurant_id=2,
            )
        self._advance_kitchen(
            other_order["id"],
            "served",
            restaurant_id=2,
        )
        with self.client_as(3) as waiter:
            idor = waiter.post(
                f"/api/orders/2/{other_order['id']}/fulfill"
            )
        self.assertEqual(idor.status_code, 403)
        self.assertEqual(
            idor.json()["error"]["code"],
            "restaurant_access_denied",
        )

        with self.client_as(1, active_restaurant_id=2) as multi_owner:
            allowed = multi_owner.post(
                f"/api/orders/2/{other_order['id']}/fulfill"
            )
        self.assertEqual(allowed.status_code, 200, allowed.text)

        with self.client_as(3) as waiter:
            revoked_order = self._create_order(waiter)
        self._advance_kitchen(revoked_order["id"], "served")
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
                f"/api/orders/1/{revoked_order['id']}/fulfill"
            )
        self.assertEqual(revoked.status_code, 403)
        self.assertEqual(
            revoked.json()["error"]["code"],
            "restaurant_access_denied",
        )
        self.assertEqual(
            self._effect_counts(restaurant_id=1)["fulfillments"],
            0,
        )

    def test_multiple_orders_in_one_session_fulfill_independently(self):
        with self.client_as(3) as waiter:
            first = self._create_order(waiter)
            second = self._create_order(waiter, quantities=[2])
        self._advance_kitchen(first["id"], "served")
        self._advance_kitchen(second["id"], "served")
        with self.client_as(3) as waiter:
            first_result = waiter.post(
                f"/api/orders/1/{first['id']}/fulfill"
            )
            second_result = waiter.post(
                f"/api/orders/1/{second['id']}/fulfill"
            )
        self.assertEqual(first_result.status_code, 200, first_result.text)
        self.assertEqual(second_result.status_code, 200, second_result.text)
        self.assertNotEqual(
            first_result.json()["fulfillment_id"],
            second_result.json()["fulfillment_id"],
        )
        with self.SessionTesting() as db:
            session = db.get(ServiceSession, self.session_ids[1])
            fulfillment_count = db.scalar(
                select(func.count()).select_from(OrderFulfillment)
            )
            inventory = db.get(
                InventoryItem,
                self.inventory_ids["primary_1"],
            )
        self.assertEqual(session.status, "open")
        self.assertEqual(fulfillment_count, 2)
        self.assertEqual(inventory.current_stock, 94)
