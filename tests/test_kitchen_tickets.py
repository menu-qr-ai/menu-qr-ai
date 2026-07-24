import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    AnalyticsEvent,
    Category,
    Dish,
    InventoryMovement,
    KitchenTicket,
    KitchenTicketLine,
    Order,
    OrderLine,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    User,
    Zone,
)


class KitchenTicketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/kitchen.db",
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
                    Restaurant(id=1, name="Centro", slug="kitchen-centro"),
                    Restaurant(id=2, name="Playa", slug="kitchen-playa"),
                ]
            )
            roles = ("owner", "manager", "waiter", "cook", "viewer", "owner")
            for user_id, role in enumerate(roles, start=1):
                restaurant_id = 1 if user_id < 6 else 2
                db.add(
                    User(
                        id=user_id,
                        email=f"kitchen-{user_id}@hostai.test",
                        hashed_password="not-used",
                        full_name=f"Kitchen {role.title()}",
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
            db.execute(delete(KitchenTicketLine))
            db.execute(delete(KitchenTicket))
            db.execute(delete(OrderLine))
            db.execute(delete(Order))
            db.execute(delete(ServiceSession))
            db.execute(delete(RestaurantTable))
            db.execute(delete(Zone))
            db.execute(delete(Dish))
            db.execute(delete(Category))
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
                db.add(
                    Dish(
                        restaurant_id=restaurant_id,
                        category_id=category.id,
                        name=f"Dish {restaurant_id}",
                        price=12.5,
                    )
                )
                table = RestaurantTable(
                    restaurant_id=restaurant_id,
                    zone_id=zone.id,
                    code=f"M{restaurant_id}",
                    capacity=4,
                )
                db.add(table)
                db.flush()
                db.add(
                    ServiceSession(
                        restaurant_id=restaurant_id,
                        table_id=table.id,
                        status="open",
                        opened_at=datetime.utcnow(),
                        guest_count=2,
                        opened_by_user_id=1 if restaurant_id == 1 else 6,
                    )
                )
            db.commit()

    @contextmanager
    def client_as(self, user_id: int, *, active_restaurant_id: int = 1):
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
            email=f"kitchen-{user_id}@hostai.test",
            hashed_password="not-used",
            full_name=f"Kitchen {roles[user_id].title()}",
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

    def _session_id(self, restaurant_id: int = 1) -> int:
        with self.SessionTesting() as db:
            return db.scalar(
                select(ServiceSession.id).where(
                    ServiceSession.restaurant_id == restaurant_id
                )
            )

    def _dish_id(self, restaurant_id: int = 1) -> int:
        with self.SessionTesting() as db:
            return db.scalar(
                select(Dish.id).where(Dish.restaurant_id == restaurant_id)
            )

    def _create_order(
        self,
        client: TestClient,
        *,
        restaurant_id: int = 1,
        note: str = "No onion",
    ) -> dict:
        order = client.post(
            f"/api/orders/{restaurant_id}/sessions/{self._session_id(restaurant_id)}",
            json={},
        )
        self.assertEqual(order.status_code, 201, order.text)
        response = client.post(
            f"/api/orders/{restaurant_id}/{order.json()['id']}/lines",
            json={
                "dish_id": self._dish_id(restaurant_id),
                "quantity": 2,
                "note": note,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _submit_ticket(
        self,
        client: TestClient,
        *,
        restaurant_id: int = 1,
    ) -> tuple[dict, dict]:
        order = self._create_order(client, restaurant_id=restaurant_id)
        submitted = client.post(
            f"/api/orders/{restaurant_id}/{order['id']}/submit"
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        ticket = client.get(
            f"/api/kitchen/{restaurant_id}/orders/{order['id']}/ticket"
        )
        self.assertEqual(ticket.status_code, 200, ticket.text)
        return order, ticket.json()

    def test_draft_has_no_ticket_and_submit_creates_snapshot_lines(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
            missing = waiter.get(f"/api/kitchen/1/orders/{order['id']}/ticket")
            submitted = waiter.post(f"/api/orders/1/{order['id']}/submit")
            ticket = waiter.get(f"/api/kitchen/1/orders/{order['id']}/ticket")

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(ticket.status_code, 200)
        payload = ticket.json()
        self.assertEqual(payload["order_id"], order["id"])
        self.assertEqual(payload["service_session_id"], order["service_session_id"])
        self.assertEqual(payload["table_code"], "M1")
        self.assertEqual(payload["zone_name"], "Zone 1")
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(len(payload["lines"]), 1)
        self.assertEqual(payload["lines"][0]["order_line_id"], order["lines"][0]["id"])
        self.assertEqual(payload["lines"][0]["dish_name"], "Dish 1")
        self.assertEqual(payload["lines"][0]["quantity"], 2)
        self.assertEqual(payload["lines"][0]["note"], "No onion")
        self.assertNotIn("unit_price", payload["lines"][0])

    def test_repeated_submit_is_idempotent_and_rounds_get_distinct_tickets(self):
        with self.client_as(3) as waiter:
            first_order = self._create_order(waiter)
            first_submit = waiter.post(f"/api/orders/1/{first_order['id']}/submit")
            second_submit = waiter.post(f"/api/orders/1/{first_order['id']}/submit")
            first_ticket = waiter.get(
                f"/api/kitchen/1/orders/{first_order['id']}/ticket"
            ).json()
            second_order = self._create_order(waiter, note="Second round")
            waiter.post(f"/api/orders/1/{second_order['id']}/submit")
            tickets = waiter.get("/api/kitchen/1/tickets")

        self.assertEqual(first_submit.status_code, 200)
        self.assertEqual(second_submit.status_code, 200)
        self.assertEqual(tickets.status_code, 200)
        self.assertEqual(len(tickets.json()), 2)
        self.assertEqual(
            sum(item["order_id"] == first_order["id"] for item in tickets.json()),
            1,
        )
        self.assertEqual(first_ticket["order_id"], first_order["id"])

    def test_database_constraints_reject_duplicate_ticket_and_line(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
            waiter.post(f"/api/orders/1/{order['id']}/submit")

        with self.SessionTesting() as db:
            ticket = db.scalar(select(KitchenTicket))
            duplicate = KitchenTicket(
                restaurant_id=1,
                order_id=ticket.order_id,
                service_session_id=ticket.service_session_id,
                table_id=ticket.table_id,
                status="pending",
                created_by_user_id=3,
            )
            db.add(duplicate)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            duplicate_line = KitchenTicketLine(
                restaurant_id=1,
                kitchen_ticket_id=ticket.id,
                order_line_id=ticket.lines[0].order_line_id,
                dish_id=ticket.lines[0].dish_id,
                dish_name="Duplicate",
                quantity=1,
                status="pending",
            )
            db.add(duplicate_line)
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_ticket_failure_rolls_back_order_submission(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
            with patch(
                "app.services.kitchen_ticket_service._copy_order_lines",
                side_effect=RuntimeError("copy failed"),
            ):
                response = waiter.post(f"/api/orders/1/{order['id']}/submit")

        with self.SessionTesting() as db:
            persisted_order = db.get(Order, order["id"])
            ticket_count = db.scalar(select(func.count()).select_from(KitchenTicket))

        self.assertEqual(response.status_code, 500)
        self.assertEqual(persisted_order.status, "draft")
        self.assertIsNone(persisted_order.submitted_at)
        self.assertEqual(ticket_count, 0)

    def test_cancelled_order_cannot_generate_ticket(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
            cancelled = waiter.post(f"/api/orders/1/{order['id']}/cancel")
            submit = waiter.post(f"/api/orders/1/{order['id']}/submit")
            ticket = waiter.get(f"/api/kitchen/1/orders/{order['id']}/ticket")

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(submit.status_code, 409)
        self.assertEqual(ticket.status_code, 404)

    def test_ticket_ids_and_order_ids_are_tenant_isolated(self):
        with self.client_as(1) as owner:
            order_one = self._create_order(owner, restaurant_id=1)
            owner.post(f"/api/orders/1/{order_one['id']}/submit")
            order_two = self._create_order(owner, restaurant_id=2)
            owner.post(f"/api/orders/2/{order_two['id']}/submit")
            ticket_two = owner.get(
                f"/api/kitchen/2/orders/{order_two['id']}/ticket"
            ).json()
            wrong_ticket = owner.get(f"/api/kitchen/1/tickets/{ticket_two['id']}")
            wrong_order = owner.get(
                f"/api/kitchen/1/orders/{order_two['id']}/ticket"
            )

        self.assertEqual(wrong_ticket.status_code, 404)
        self.assertEqual(wrong_order.status_code, 404)

    def test_roles_can_read_but_only_kitchen_roles_can_operate(self):
        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
            waiter.post(f"/api/orders/1/{order['id']}/submit")

        for user_id in (1, 2, 3, 4, 5):
            with self.subTest(user_id=user_id), self.client_as(user_id) as client:
                response = client.get("/api/kitchen/1/tickets")
                self.assertEqual(response.status_code, 200, response.text)

        with self.client_as(2) as manager:
            unauthorized = manager.get("/api/kitchen/2/tickets")
        self.assertEqual(unauthorized.status_code, 403)

    def test_submission_does_not_touch_inventory_sales_or_analytics(self):
        with self.SessionTesting() as db:
            movement_count = db.scalar(select(func.count()).select_from(InventoryMovement))
            event_count = db.scalar(select(func.count()).select_from(AnalyticsEvent))

        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
            response = waiter.post(f"/api/orders/1/{order['id']}/submit")

        with self.SessionTesting() as db:
            self.assertEqual(
                db.scalar(select(func.count()).select_from(InventoryMovement)),
                movement_count,
            )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(AnalyticsEvent)),
                event_count,
            )
        self.assertEqual(response.status_code, 200)

    def test_kitchen_tables_compile_for_postgresql(self):
        for table_name in ("kitchen_tickets", "kitchen_ticket_lines"):
            with self.subTest(table=table_name):
                sql = str(
                    CreateTable(Base.metadata.tables[table_name]).compile(
                        dialect=postgresql.dialect(),
                    )
                )
                self.assertIn(f"CREATE TABLE {table_name}", sql)

    def test_ticket_status_flow_is_idempotent_and_preserves_timestamps(self):
        with self.client_as(3) as waiter:
            _, ticket = self._submit_ticket(waiter)

        with self.client_as(4) as cook:
            started = cook.post(f"/api/kitchen/1/tickets/{ticket['id']}/start")
            started_again = cook.post(
                f"/api/kitchen/1/tickets/{ticket['id']}/start"
            )
            ready = cook.post(f"/api/kitchen/1/tickets/{ticket['id']}/ready")
            ready_again = cook.post(
                f"/api/kitchen/1/tickets/{ticket['id']}/ready"
            )
            served = cook.post(f"/api/kitchen/1/tickets/{ticket['id']}/serve")
            served_again = cook.post(
                f"/api/kitchen/1/tickets/{ticket['id']}/serve"
            )

        self.assertEqual(started.json()["status"], "preparing")
        self.assertEqual(started.json()["started_at"], started_again.json()["started_at"])
        self.assertEqual(ready.json()["status"], "ready")
        self.assertEqual(ready.json()["ready_at"], ready_again.json()["ready_at"])
        self.assertEqual(served.json()["status"], "served")
        self.assertEqual(served.json()["served_at"], served_again.json()["served_at"])
        self.assertEqual(served.json()["lines"][0]["status"], "served")
        self.assertIsNotNone(served.json()["lines"][0]["started_at"])
        self.assertIsNotNone(served.json()["lines"][0]["ready_at"])
        self.assertIsNotNone(served.json()["lines"][0]["served_at"])

    def test_independent_lines_drive_aggregate_status(self):
        with self.SessionTesting() as db:
            category_id = db.scalar(
                select(Category.id).where(Category.restaurant_id == 1)
            )
            second_dish = Dish(
                restaurant_id=1,
                category_id=category_id,
                name="Second dish",
                price=8,
            )
            db.add(second_dish)
            db.commit()
            second_dish_id = second_dish.id

        with self.client_as(3) as waiter:
            order = self._create_order(waiter)
            second_line = waiter.post(
                f"/api/orders/1/{order['id']}/lines",
                json={"dish_id": second_dish_id, "quantity": 1},
            )
            waiter.post(f"/api/orders/1/{order['id']}/submit")
            ticket = waiter.get(
                f"/api/kitchen/1/orders/{order['id']}/ticket"
            ).json()

        first_line_id = ticket["lines"][0]["id"]
        second_line_id = ticket["lines"][1]["id"]
        with self.client_as(4) as cook:
            first_started = cook.post(
                f"/api/kitchen/1/tickets/{ticket['id']}/lines/{first_line_id}/start"
            )
            first_ready = cook.post(
                f"/api/kitchen/1/tickets/{ticket['id']}/lines/{first_line_id}/ready"
            )
            premature_ticket_ready = cook.post(
                f"/api/kitchen/1/tickets/{ticket['id']}/ready"
            )
            cook.post(
                f"/api/kitchen/1/tickets/{ticket['id']}/lines/{second_line_id}/start"
            )
            all_ready = cook.post(
                f"/api/kitchen/1/tickets/{ticket['id']}/lines/{second_line_id}/ready"
            )

        self.assertEqual(second_line.status_code, 200)
        self.assertEqual(first_started.json()["status"], "preparing")
        self.assertEqual(first_ready.json()["status"], "preparing")
        self.assertEqual(premature_ticket_ready.status_code, 409)
        self.assertEqual(
            premature_ticket_ready.json()["error"]["code"],
            "kitchen_lines_pending",
        )
        self.assertEqual(all_ready.json()["status"], "ready")
        self.assertIsNotNone(all_ready.json()["ready_at"])

    def test_ticket_and_line_cancellation_rules(self):
        with self.client_as(3) as waiter:
            _, pending_ticket = self._submit_ticket(waiter)
            _, preparing_ticket = self._submit_ticket(waiter)
            _, ready_ticket = self._submit_ticket(waiter)

        with self.client_as(4) as cook:
            pending_cancelled = cook.post(
                f"/api/kitchen/1/tickets/{pending_ticket['id']}/cancel"
            )
            cook.post(
                f"/api/kitchen/1/tickets/{preparing_ticket['id']}/start"
            )
            preparing_cancelled = cook.post(
                f"/api/kitchen/1/tickets/{preparing_ticket['id']}/cancel"
            )
            cook.post(f"/api/kitchen/1/tickets/{ready_ticket['id']}/start")
            cook.post(f"/api/kitchen/1/tickets/{ready_ticket['id']}/ready")
            rejected = cook.post(
                f"/api/kitchen/1/tickets/{ready_ticket['id']}/cancel"
            )

        self.assertEqual(pending_cancelled.json()["status"], "cancelled")
        self.assertEqual(preparing_cancelled.json()["status"], "cancelled")
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(
            rejected.json()["error"]["code"],
            "kitchen_cancellation_not_allowed",
        )

    def test_order_cancellation_is_atomic_before_kitchen_starts(self):
        with self.client_as(3) as waiter:
            order, ticket = self._submit_ticket(waiter)
            cancelled_order = waiter.post(f"/api/orders/1/{order['id']}/cancel")
            cancelled_ticket = waiter.get(
                f"/api/kitchen/1/tickets/{ticket['id']}"
            )
            second_order, second_ticket = self._submit_ticket(waiter)

        with self.client_as(4) as cook:
            cook.post(f"/api/kitchen/1/tickets/{second_ticket['id']}/start")

        with self.client_as(3) as waiter:
            rejected = waiter.post(f"/api/orders/1/{second_order['id']}/cancel")
            still_active = waiter.get(
                f"/api/kitchen/1/tickets/{second_ticket['id']}"
            )

        self.assertEqual(cancelled_order.json()["status"], "cancelled")
        self.assertEqual(cancelled_ticket.json()["status"], "cancelled")
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(
            rejected.json()["error"]["code"],
            "kitchen_cancellation_not_allowed",
        )
        self.assertEqual(still_active.json()["status"], "preparing")

    def test_only_owner_manager_and_cook_can_operate_kitchen(self):
        with self.client_as(3) as waiter:
            _, owner_ticket = self._submit_ticket(waiter)
            _, manager_ticket = self._submit_ticket(waiter)
            _, cook_ticket = self._submit_ticket(waiter)
            _, denied_ticket = self._submit_ticket(waiter)

        operations = (
            (1, owner_ticket["id"], 200),
            (2, manager_ticket["id"], 200),
            (4, cook_ticket["id"], 200),
            (3, denied_ticket["id"], 403),
            (5, denied_ticket["id"], 403),
        )
        for user_id, ticket_id, expected in operations:
            with self.subTest(user_id=user_id), self.client_as(user_id) as client:
                response = client.post(
                    f"/api/kitchen/1/tickets/{ticket_id}/start"
                )
                self.assertEqual(response.status_code, expected, response.text)

    def test_kitchen_action_idor_is_rejected(self):
        with self.client_as(1) as owner:
            _, ticket_one = self._submit_ticket(owner, restaurant_id=1)
            _, ticket_two = self._submit_ticket(owner, restaurant_id=2)
            wrong_ticket = owner.post(
                f"/api/kitchen/1/tickets/{ticket_two['id']}/start"
            )
            wrong_line = owner.post(
                f"/api/kitchen/1/tickets/{ticket_one['id']}/lines/"
                f"{ticket_two['lines'][0]['id']}/start"
            )

        self.assertEqual(wrong_ticket.status_code, 404)
        self.assertEqual(wrong_line.status_code, 404)

    def test_transition_failure_rolls_back_line_and_ticket(self):
        with self.client_as(3) as waiter:
            _, ticket = self._submit_ticket(waiter)

        with self.client_as(4) as cook:
            with patch(
                "app.services.kitchen_ticket_service._recalculate_ticket_status",
                side_effect=RuntimeError("aggregate failed"),
            ):
                response = cook.post(
                    f"/api/kitchen/1/tickets/{ticket['id']}/lines/"
                    f"{ticket['lines'][0]['id']}/start"
                )

        with self.SessionTesting() as db:
            persisted_ticket = db.get(KitchenTicket, ticket["id"])
            persisted_line = db.get(KitchenTicketLine, ticket["lines"][0]["id"])

        self.assertEqual(response.status_code, 500)
        self.assertEqual(persisted_ticket.status, "pending")
        self.assertEqual(persisted_line.status, "pending")
        self.assertIsNone(persisted_ticket.started_at)
        self.assertIsNone(persisted_line.started_at)

    def test_served_ticket_requires_fulfillment_to_complete_order(self):
        with self.client_as(3) as waiter:
            order, ticket = self._submit_ticket(waiter)
            premature = waiter.post(f"/api/orders/1/{order['id']}/complete")

        with self.client_as(4) as cook:
            cook.post(f"/api/kitchen/1/tickets/{ticket['id']}/start")
            cook.post(f"/api/kitchen/1/tickets/{ticket['id']}/ready")
            cook.post(f"/api/kitchen/1/tickets/{ticket['id']}/serve")

        with self.SessionTesting() as db:
            order_before_completion = db.get(Order, order["id"])
            status_before_completion = order_before_completion.status

        with self.client_as(3) as waiter:
            completion_bypass = waiter.post(
                f"/api/orders/1/{order['id']}/complete"
            )

        self.assertEqual(premature.status_code, 409)
        self.assertEqual(
            premature.json()["error"]["code"],
            "kitchen_ticket_not_served",
        )
        self.assertEqual(status_before_completion, "submitted")
        self.assertEqual(completion_bypass.status_code, 409)
        self.assertEqual(
            completion_bypass.json()["error"]["code"],
            "order_fulfillment_required",
        )

    def test_kitchen_transitions_do_not_touch_inventory_or_analytics(self):
        with self.SessionTesting() as db:
            movement_count = db.scalar(select(func.count()).select_from(InventoryMovement))
            event_count = db.scalar(select(func.count()).select_from(AnalyticsEvent))

        with self.client_as(3) as waiter:
            _, ticket = self._submit_ticket(waiter)
        with self.client_as(4) as cook:
            cook.post(f"/api/kitchen/1/tickets/{ticket['id']}/start")
            cook.post(f"/api/kitchen/1/tickets/{ticket['id']}/ready")
            cook.post(f"/api/kitchen/1/tickets/{ticket['id']}/serve")

        with self.SessionTesting() as db:
            movements_after = db.scalar(
                select(func.count()).select_from(InventoryMovement)
            )
            events_after = db.scalar(select(func.count()).select_from(AnalyticsEvent))

        self.assertEqual(movements_after, movement_count)
        self.assertEqual(events_after, event_count)
