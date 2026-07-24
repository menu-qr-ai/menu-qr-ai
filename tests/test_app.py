import json
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import AppError
from app.core.security import hash_password
from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    AnalyticsEvent,
    Category,
    Dish,
    DishIngredient,
    InventoryAlert,
    InventoryInsight,
    InventoryItem,
    InventoryMovement,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    User,
    Zone,
)
from app.services.technical_recipe_service import get_recipe, require_recipe_items
from app.utils.demo_seed import DEMO_SLUG, seed_demo_database


class AppSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        cls.seed_database()

        def override_get_db():
            db = cls.SessionTesting()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: cls.auth_user
        app.dependency_overrides[get_active_restaurant_id] = lambda: 1

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()
        cls.temp_dir.cleanup()

    @classmethod
    def seed_database(cls):
        with cls.SessionTesting() as db:
            restaurant = Restaurant(id=1, name="Demo Restaurant", slug="demo-restaurant")
            user = User(
                id=1,
                email="regression-owner@hostai.local",
                hashed_password=hash_password("Regression-owner-2026"),
                full_name="Regression Owner",
                role="owner",
                restaurant_id=1,
                is_active=True,
            )
            membership = RestaurantMembership(
                id=1,
                user_id=1,
                restaurant_id=1,
                role="owner",
                is_active=True,
                created_by_user_id=1,
            )
            category = Category(id=1, name="Pizzas", restaurant_id=1)
            dish = Dish(
                id=1,
                name="Pizza Margarita",
                description="Classic pizza with tomato and cheese",
                price=9.99,
                ingredients="Tomato, mozzarella, basil",
                allergens="Gluten, lactose",
                image="",
                category_id=1,
                restaurant_id=1,
            )
            db.add_all([restaurant, user, membership, category, dish])
            db.commit()
        cls.auth_user = User(
            id=1,
            email="regression-owner@hostai.local",
            hashed_password="not-used",
            full_name="Regression Owner",
            role="owner",
            restaurant_id=1,
            is_active=True,
            created_at=datetime.utcnow(),
        )

    def setUp(self):
        with self.SessionTesting() as db:
            db.execute(delete(AnalyticsEvent))
            db.execute(delete(InventoryMovement))
            db.execute(delete(DishIngredient))
            db.execute(delete(InventoryAlert))
            db.execute(delete(InventoryInsight))
            db.execute(delete(InventoryItem))
            db.commit()

    def test_health_route_works(self):
        with TestClient(app) as client:
            response = client.get("/test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_health_route_checks_database(self):
        with TestClient(app) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "ok")
        self.assertIn("version", response.json())
        self.assertIn("analytics", response.json())
        self.assertIn("restaurants", response.json())

    def test_demo_seed_is_idempotent(self):
        with self.SessionTesting() as db:
            first = seed_demo_database(db)
            first_counts = {
                "restaurants": db.scalar(select(func.count()).select_from(Restaurant)),
                "categories": db.scalar(select(func.count()).select_from(Category)),
                "dishes": db.scalar(select(func.count()).select_from(Dish)),
                "events": db.scalar(select(func.count()).select_from(AnalyticsEvent)),
                "inventory_items": db.scalar(select(func.count()).select_from(InventoryItem)),
                "dish_ingredients": db.scalar(select(func.count()).select_from(DishIngredient)),
                "inventory_movements": db.scalar(select(func.count()).select_from(InventoryMovement)),
            }
            second = seed_demo_database(db)
            second_counts = {
                "restaurants": db.scalar(select(func.count()).select_from(Restaurant)),
                "categories": db.scalar(select(func.count()).select_from(Category)),
                "dishes": db.scalar(select(func.count()).select_from(Dish)),
                "events": db.scalar(select(func.count()).select_from(AnalyticsEvent)),
                "inventory_items": db.scalar(select(func.count()).select_from(InventoryItem)),
                "dish_ingredients": db.scalar(select(func.count()).select_from(DishIngredient)),
                "inventory_movements": db.scalar(select(func.count()).select_from(InventoryMovement)),
            }

        self.assertEqual(first["slug"], DEMO_SLUG)
        self.assertEqual(second["slug"], DEMO_SLUG)
        self.assertEqual(first_counts, second_counts)

    def test_demo_seed_creates_demo_restaurant(self):
        with self.SessionTesting() as db:
            seed_demo_database(db)
            restaurant = db.scalar(select(Restaurant).where(Restaurant.slug == DEMO_SLUG))

        self.assertIsNotNone(restaurant)
        self.assertEqual(restaurant.name, "Demo Restaurant")
        self.assertTrue(restaurant.is_active)

    def test_demo_seed_public_slug_is_accessible(self):
        with self.SessionTesting() as db:
            seed_demo_database(db)

        with TestClient(app) as client:
            response = client.get(f"/r/{DEMO_SLUG}/menu")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Demo Restaurant", response.text)

    def test_demo_short_slug_menu_is_accessible(self):
        with self.SessionTesting() as db:
            seed_demo_database(db)

        with TestClient(app) as client:
            response = client.get("/r/demo/menu")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Demo Restaurant", response.text)

    def test_openapi_exposes_public_menu_route(self):
        with TestClient(app) as client:
            response = client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("/r/{slug}/menu", response.json()["paths"])

    def test_dashboard_responds_after_demo_seed(self):
        with self.SessionTesting() as db:
            result = seed_demo_database(db)

        with TestClient(app) as client:
            response = client.get(f"/api/dashboard/summary?restaurant_id={result['restaurant_id']}&range=30d")

        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json()["summary"]["total_menu_views"], 0)

    def test_demo_seed_creates_inventory_demo_data(self):
        with self.SessionTesting() as db:
            result = seed_demo_database(db)
            item_count = db.scalar(select(func.count()).select_from(InventoryItem))
            relation_count = db.scalar(select(func.count()).select_from(DishIngredient))
            movement_count = db.scalar(select(func.count()).select_from(InventoryMovement))
            valued_movement_count = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.historical_unit_cost.is_not(None),
                    InventoryMovement.historical_total_cost.is_not(None),
                )
            )

        self.assertEqual(result["inventory_items"], 10)
        self.assertEqual(item_count, 10)
        self.assertGreaterEqual(relation_count, 10)
        self.assertEqual(movement_count, 10)
        self.assertEqual(valued_movement_count, 10)

    def test_demo_seed_creates_dining_room_without_overwriting_existing_tables(self):
        with self.SessionTesting() as db:
            first = seed_demo_database(db)
            custom_table = RestaurantTable(
                restaurant_id=first["restaurant_id"],
                code="VIP",
                capacity=8,
            )
            db.add(custom_table)
            db.commit()

            second = seed_demo_database(db)
            zone_count = db.scalar(select(func.count()).select_from(Zone))
            table_count = db.scalar(select(func.count()).select_from(RestaurantTable))
            zone_names = set(db.scalars(select(Zone.name)))
            table_codes = set(db.scalars(select(RestaurantTable.code)))
            preserved_table = db.scalar(
                select(RestaurantTable).where(RestaurantTable.code == "VIP")
            )

        self.assertEqual(second["dining_zones_created"], 0)
        self.assertEqual(second["dining_tables_created"], 0)
        self.assertEqual(zone_count, 2)
        self.assertEqual(table_count, 6)
        self.assertEqual(zone_names, {"Interior", "Terraza"})
        self.assertTrue({"M01", "M02", "M03", "T01", "T02"}.issubset(table_codes))
        self.assertIsNotNone(preserved_table)

    def test_api_root_exposes_environment(self):
        with TestClient(app) as client:
            response = client.get("/api")

        self.assertEqual(response.status_code, 200)
        self.assertIn("name", response.json())

    def test_api_plans_are_available(self):
        with TestClient(app) as client:
            response = client.get("/api/plans")

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["plans"]), 3)

    def test_restaurants_endpoint_uses_schema(self):
        with TestClient(app) as client:
            response = client.get("/restaurants")

        self.assertEqual(response.status_code, 200)
        self.assertIn("id", response.json()[0])

    def test_api_restaurant_can_be_created(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/restaurants",
                json={"name": "Casa Sprint", "city": "Madrid", "default_language": "es"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["name"], "Casa Sprint")
        self.assertEqual(payload["slug"], "casa-sprint")
        self.assertEqual(payload["city"], "Madrid")

    def test_api_restaurants_can_be_listed(self):
        with TestClient(app) as client:
            response = client.get("/api/restaurants")

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()), 1)

    def test_api_restaurant_can_be_loaded_by_slug(self):
        with TestClient(app) as client:
            created = client.post("/api/restaurants", json={"name": "Slug Bistro"}).json()
            response = client.get(f"/api/restaurants/by-slug/{created['slug']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], created["id"])

    def test_api_restaurant_settings_can_be_updated(self):
        with TestClient(app) as client:
            created = client.post("/api/restaurants", json={"name": "Settings Cafe"}).json()
            response = client.patch(
                f"/api/restaurants/{created['id']}",
                json={
                    "description": "Menu premium",
                    "primary_color": "#111827",
                    "currency": "usd",
                    "default_language": "en",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["description"], "Menu premium")
        self.assertEqual(payload["primary_color"], "#111827")
        self.assertEqual(payload["currency"], "usd")
        self.assertEqual(payload["default_language"], "en")

    def test_menu_page_renders_with_assets_and_data(self):
        with TestClient(app) as client:
            response = client.get("/menu")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Platos disponibles", response.text)
        self.assertIn("languageSelect", response.text)
        self.assertIn("menuSearch", response.text)
        self.assertIn("window.menuData", response.text)

    def test_public_slug_menu_renders_for_restaurant(self):
        with TestClient(app) as client:
            created = client.post("/api/restaurants", json={"name": "Public Menu House"}).json()
            response = client.get(f"/r/{created['slug']}/menu")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Public Menu House", response.text)
        self.assertIn(f'href="/r/{created["slug"]}/menu"', response.text)
        self.assertIn(f"restaurantId: {created['id']}", response.text)

    def test_public_slug_menu_returns_404_when_missing(self):
        with TestClient(app) as client:
            response = client.get("/r/slug-inexistente/menu")

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("detail", response.json())
        self.assertEqual(response.json()["error"]["code"], "restaurant_not_found")

    def test_menu_tracking_uses_real_restaurant_id(self):
        with TestClient(app) as client:
            created = client.post("/api/restaurants", json={"name": "Tracking Table"}).json()
            response = client.get(f"/r/{created['slug']}/menu")

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"restaurantId: {created['id']}", response.text)
        self.assertIn('"id": ' + str(created["id"]), response.text)

    def test_admin_dashboard_renders(self):
        with TestClient(app) as client:
            response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Panel de administracion", response.text)
        self.assertIn("Suscripciones", response.text)
        self.assertIn("Analitica", response.text)

    def test_admin_restaurants_page_renders(self):
        with TestClient(app) as client:
            response = client.get("/admin/restaurants")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Restaurantes", response.text)

    def test_admin_restaurant_settings_page_renders(self):
        with TestClient(app) as client:
            created = client.post("/api/restaurants", json={"name": "Admin Settings"}).json()
            response = client.get(f"/admin/restaurants/{created['id']}/settings")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Admin Settings", response.text)
        self.assertIn("PATCH /api/restaurants", response.text)

    def test_static_assets_are_served(self):
        with TestClient(app) as client:
            css_response = client.get("/static/css/style.css")
            js_response = client.get("/static/js/app.js")

        self.assertEqual(css_response.status_code, 200)
        self.assertEqual(js_response.status_code, 200)

    def test_ai_route_is_stable_without_openai_key(self):
        with TestClient(app) as client:
            response = client.get("/ai/translate-dish/1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"error": "No OPENAI_API_KEY"})

    def test_analytics_event_can_be_created(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/analytics/events",
                json={
                    "restaurant_id": 1,
                    "event_type": "menu_view",
                    "language": "en",
                    "metadata": {"source": "test"},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["event_type"], "menu_view")
        self.assertEqual(payload["metadata"], {"source": "test"})
        self.assertIn("created_at", payload)

    def test_analytics_event_accepts_minimal_body(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/analytics/events",
                json={"event_type": "menu_view"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["event_type"], "menu_view")
        self.assertIsNone(payload["restaurant_id"])
        self.assertIsNone(payload["dish_id"])
        self.assertIsNone(payload["language"])
        self.assertIsNone(payload["metadata"])

    def test_analytics_event_accepts_full_body_with_nulls(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/analytics/events",
                json={
                    "restaurant_id": 1,
                    "event_type": "menu_view",
                    "dish_id": None,
                    "language": "es",
                    "metadata": {"source": "swagger"},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["restaurant_id"], 1)
        self.assertEqual(payload["event_type"], "menu_view")
        self.assertIsNone(payload["dish_id"])
        self.assertEqual(payload["language"], "es")
        self.assertEqual(payload["metadata"], {"source": "swagger"})

    def test_analytics_event_rejects_invalid_type(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/analytics/events",
                json={"restaurant_id": 1, "event_type": "bad_event"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_analytics_event_type")

    def test_recent_analytics_events_returns_list(self):
        with TestClient(app) as client:
            client.post("/api/analytics/events", json={"restaurant_id": 1, "event_type": "menu_view"})
            response = client.get("/api/analytics/events/recent?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_analytics_events_count_returns_counter(self):
        with TestClient(app) as client:
            client.post("/api/analytics/events", json={"restaurant_id": 1, "event_type": "search"})
            client.post("/api/analytics/events", json={"restaurant_id": 1, "event_type": "search"})
            response = client.get("/api/analytics/events/count?event_type=search&restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)

    def test_dashboard_summary_returns_empty_state_without_events(self):
        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["total_menu_views"], 0)
        self.assertEqual(payload["top_dishes"], [])
        self.assertEqual(payload["top_searches"], [])
        self.assertEqual(payload["insights"][0]["title"], "No hay suficientes datos todavia")

    def test_dashboard_summary_changes_with_analytics_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="search",
                        metadata_json=json.dumps({"search_query": "pizza"}),
                    ),
                    AnalyticsEvent(restaurant_id=1, event_type="language_change", language="en"),
                    AnalyticsEvent(restaurant_id=1, event_type="translation_request", language="en"),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["total_menu_views"], 1)
        self.assertEqual(payload["summary"]["total_dish_views"], 2)
        self.assertEqual(payload["summary"]["total_searches"], 1)
        self.assertEqual(payload["summary"]["total_language_changes"], 1)
        self.assertEqual(payload["summary"]["total_translation_requests"], 1)
        self.assertEqual(payload["summary"]["dish_view_menu_view_ratio"], 2)
        self.assertEqual(payload["summary"]["top_dish_name"], "Pizza Margarita")
        self.assertEqual(payload["top_dishes"][0]["name"], "Pizza Margarita")
        self.assertEqual(payload["top_dishes"][0]["views"], 2)
        self.assertEqual(payload["top_searches"][0], {"query": "pizza", "count": 1})
        self.assertEqual(payload["languages"][0], {"language": "en", "count": 2, "percentage": 100.0})
        self.assertGreaterEqual(len(payload["events_by_day"]), 1)

    def test_dashboard_summary_filters_by_restaurant_id(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=2, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=2, event_type="menu_view"),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?restaurant_id=2")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["restaurant_id"], 2)
        self.assertEqual(payload["summary"]["total_menu_views"], 2)

    def test_dashboard_page_includes_restaurant_selector(self):
        with TestClient(app) as client:
            response = client.get("/admin/dashboard?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("restaurantSelect", response.text)
        self.assertIn("Demo Restaurant", response.text)

    def test_dashboard_range_today_filters_events(self):
        old_date = datetime.utcnow() - timedelta(days=2)
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view", created_at=old_date),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=today")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["range"], "today")
        self.assertEqual(payload["summary"]["total_menu_views"], 1)

    def test_dashboard_range_7d_filters_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="search"),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="search",
                        created_at=datetime.utcnow() - timedelta(days=8),
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=7d")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["total_searches"], 1)

    def test_dashboard_range_30d_filters_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="translation_request"),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="translation_request",
                        created_at=datetime.utcnow() - timedelta(days=31),
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=30d")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["total_translation_requests"], 1)

    def test_dashboard_range_90d_filters_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="menu_view",
                        created_at=datetime.utcnow() - timedelta(days=91),
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=90d")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["total_menu_views"], 1)

    def test_dashboard_range_all_includes_all_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="menu_view",
                        created_at=datetime.utcnow() - timedelta(days=120),
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["range"], "all")
        self.assertEqual(payload["summary"]["total_menu_views"], 2)

    def test_dashboard_insights_are_generated_from_real_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                    AnalyticsEvent(restaurant_id=1, event_type="language_change", language="en"),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="search",
                        metadata_json=json.dumps({"search_query": "tiramisu"}),
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=all")

        self.assertEqual(response.status_code, 200)
        insight_titles = [insight["title"] for insight in response.json()["insights"]]
        self.assertIn("Hay pocas visualizaciones de la carta", insight_titles)
        self.assertTrue(any("idioma" in title.lower() or "eventos con idioma" in title.lower() for title in insight_titles))

    def test_dashboard_page_renders_shell(self):
        with TestClient(app) as client:
            response = client.get("/admin/dashboard?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Dashboard Inteligente", response.text)
        self.assertIn("dashboard.js", response.text)

    def test_inventory_item_can_be_created_and_listed(self):
        with TestClient(app) as client:
            created = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Mozzarella",
                    "unit": "g",
                    "current_stock": 500,
                    "minimum_stock": 250,
                    "ideal_stock": 1000,
                    "cost": 4.2,
                    "supplier": "Proveedor Norte",
                },
            )
            listed = client.get("/api/inventory/items?restaurant_id=1")

        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["name"], "Mozzarella")
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(item["name"] == "Mozzarella" for item in listed.json()))

    def test_inventory_movement_updates_stock_and_records_audit(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Tomate",
                    "unit": "kg",
                    "current_stock": 4,
                    "minimum_stock": 2,
                    "ideal_stock": 8,
                },
            ).json()
            movement = client.post(
                "/api/inventory/movements",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "movement_type": "OUT",
                    "quantity": 1.5,
                    "note": "mise en place",
                },
            )
            refreshed = client.get("/api/inventory/items?restaurant_id=1")

        self.assertEqual(movement.status_code, 200)
        movement_payload = movement.json()
        self.assertEqual(movement_payload["unit"], "kg")
        self.assertEqual(movement_payload["reason"], "manual")
        tomate = next(item for item in refreshed.json() if item["name"] == "Tomate")
        self.assertEqual(tomate["current_stock"], 2.5)

    def test_inventory_item_initial_stock_creates_ledger_entry(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Ledger inicial",
                    "unit": "kg",
                    "current_stock": 7,
                    "minimum_stock": 2,
                    "ideal_stock": 10,
                },
            ).json()

        with self.SessionTesting() as db:
            movement = db.scalar(
                select(InventoryMovement).where(
                    InventoryMovement.inventory_item_id == item["id"],
                    InventoryMovement.movement_type == "IN",
                )
            )

        self.assertIsNotNone(movement)
        self.assertEqual(movement.quantity, 7)
        self.assertEqual(movement.unit, "kg")
        self.assertEqual(movement.reason, "initial_stock")
        self.assertEqual(movement.origin_type, "inventory_item")
        self.assertEqual(movement.origin_id, str(item["id"]))

    def test_inventory_movement_rejects_invalid_unit(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Unidad ledger",
                    "unit": "kg",
                    "current_stock": 3,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            response = client.post(
                "/api/inventory/movements",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "movement_type": "OUT",
                    "quantity": 1,
                    "unit": "box",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_inventory_movement_unit")

    def test_inventory_movement_rejects_zero_quantity(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Cantidad cero ledger",
                    "unit": "kg",
                    "current_stock": 3,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            response = client.post(
                "/api/inventory/movements",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "movement_type": "OUT",
                    "quantity": 0,
                },
            )

        self.assertEqual(response.status_code, 422)

    def test_inventory_movement_history_has_no_edit_api(self):
        with TestClient(app) as client:
            openapi = client.get("/openapi.json").json()

        self.assertNotIn("/api/inventory/movements/{movement_id}", openapi["paths"])

    def test_purchase_intake_increments_stock_and_creates_in_movement(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion tomate",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 6,
                },
            ).json()
            response = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 3,
                    "unit": "kg",
                    "reason": "recepcion_mercancia",
                    "reference": "ALB-1001",
                    "origin_id": "delivery-note-1001",
                },
            )
            refreshed = client.get("/api/inventory/items?restaurant_id=1").json()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["current_stock"], 5)
        self.assertEqual(payload["reference"], "ALB-1001")
        item_payload = next(entry for entry in refreshed if entry["id"] == item["id"])
        self.assertEqual(item_payload["current_stock"], 5)

        with self.SessionTesting() as db:
            movement = db.get(InventoryMovement, payload["movement_id"])

        self.assertIsNotNone(movement)
        self.assertEqual(movement.movement_type, "IN")
        self.assertEqual(movement.quantity, 3)
        self.assertEqual(movement.unit, "kg")
        self.assertEqual(movement.reason, "recepcion_mercancia")
        self.assertEqual(movement.origin_type, "purchase_intake")
        self.assertEqual(movement.origin_id, "delivery-note-1001")
        self.assertEqual(movement.reference, "ALB-1001")

    def test_purchase_intake_with_unit_cost_updates_stock_cost_and_historical_snapshot(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion coste compra",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 6,
                    "cost": 1.5,
                },
            ).json()
            response = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 3,
                    "unit": "kg",
                    "unit_cost": 2.75,
                    "reason": "recepcion_mercancia",
                    "reference": "ALB-COST-1",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["current_stock"], 5)
        self.assertEqual(payload["unit_cost"], 2.75)
        self.assertEqual(payload["historical_total_cost"], 8.25)

        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            movement = db.get(InventoryMovement, payload["movement_id"])

        self.assertEqual(refreshed_item.cost, 2.25)
        self.assertEqual(movement.historical_unit_cost, 2.75)
        self.assertEqual(movement.historical_total_cost, 8.25)
        self.assertEqual(movement.wac_previous_stock, 2)
        self.assertEqual(movement.wac_previous_unit_cost, 1.5)
        self.assertEqual(movement.wac_resulting_unit_cost, 2.25)

    def test_purchase_intake_preserves_historical_cost_after_second_reception(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion coste historico",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 6,
                },
            ).json()
            first = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 4,
                    "unit": "kg",
                    "unit_cost": 2.5,
                    "reason": "primera_recepcion",
                    "reference": "ALB-HIST-1",
                },
            ).json()
            second = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 2,
                    "unit": "kg",
                    "unit_cost": 4,
                    "reason": "segunda_recepcion",
                    "reference": "ALB-HIST-2",
                },
            ).json()

        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            first_movement = db.get(InventoryMovement, first["movement_id"])
            second_movement = db.get(InventoryMovement, second["movement_id"])

        self.assertEqual(refreshed_item.current_stock, 6)
        self.assertEqual(refreshed_item.cost, 3)
        self.assertEqual(first_movement.historical_unit_cost, 2.5)
        self.assertEqual(first_movement.historical_total_cost, 10)
        self.assertEqual(first_movement.wac_previous_stock, 0)
        self.assertIsNone(first_movement.wac_previous_unit_cost)
        self.assertEqual(first_movement.wac_resulting_unit_cost, 2.5)
        self.assertEqual(second_movement.historical_unit_cost, 4)
        self.assertEqual(second_movement.historical_total_cost, 8)
        self.assertEqual(second_movement.wac_previous_stock, 4)
        self.assertEqual(second_movement.wac_previous_unit_cost, 2.5)
        self.assertEqual(second_movement.wac_resulting_unit_cost, 3)

    def test_purchase_intake_wac_trace_reconstructs_historical_reception_after_later_changes(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion trazable WAC",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                    "cost": 2,
                },
            ).json()
            intake = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 3,
                    "unit": "kg",
                    "unit_cost": 6,
                    "reason": "recepcion_mercancia",
                    "reference": "ALB-WAC-TRACE",
                },
            ).json()
            client.patch(f"/api/inventory/items/{item['id']}", json={"cost": 9})
            client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 2,
                    "unit": "kg",
                    "unit_cost": 10,
                    "reason": "recepcion_posterior",
                    "reference": "ALB-WAC-LATER",
                },
            )

        with self.SessionTesting() as db:
            movement = db.get(InventoryMovement, intake["movement_id"])
            refreshed_item = db.get(InventoryItem, item["id"])

        reconstructed_cost = (
            movement.wac_previous_stock * movement.wac_previous_unit_cost
            + movement.quantity * movement.historical_unit_cost
        ) / (movement.wac_previous_stock + movement.quantity)
        self.assertEqual(movement.wac_previous_stock, 5)
        self.assertEqual(movement.wac_previous_unit_cost, 2)
        self.assertEqual(movement.quantity, 3)
        self.assertEqual(movement.historical_unit_cost, 6)
        self.assertEqual(movement.historical_total_cost, 18)
        self.assertEqual(movement.wac_resulting_unit_cost, 3.5)
        self.assertEqual(reconstructed_cost, movement.wac_resulting_unit_cost)
        self.assertNotEqual(refreshed_item.cost, movement.wac_resulting_unit_cost)

    def test_purchase_intake_allows_optional_reference(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion sin referencia",
                    "unit": "unit",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                    "cost": 7,
                },
            ).json()
            response = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 2,
                    "unit": "unit",
                    "reason": "compra_directa",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["reference"])
        self.assertEqual(response.json()["current_stock"], 2)
        self.assertIsNone(response.json()["unit_cost"])
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            movement = db.get(InventoryMovement, response.json()["movement_id"])

        self.assertEqual(refreshed_item.cost, 7)
        self.assertIsNone(movement.historical_unit_cost)
        self.assertIsNone(movement.historical_total_cost)
        self.assertIsNone(movement.wac_previous_stock)
        self.assertIsNone(movement.wac_previous_unit_cost)
        self.assertIsNone(movement.wac_resulting_unit_cost)

    def test_purchase_intake_rejects_invalid_quantity(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion cantidad",
                    "unit": "kg",
                    "current_stock": 1,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                },
            ).json()
            response = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 0,
                    "unit": "kg",
                    "reason": "recepcion_mercancia",
                },
            )

        self.assertEqual(response.status_code, 422)

    def test_purchase_intake_rejects_invalid_unit(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion unidad",
                    "unit": "kg",
                    "current_stock": 1,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                },
            ).json()
            response = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "box",
                    "reason": "recepcion_mercancia",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_inventory_movement_unit")

    def test_purchase_intake_rejects_invalid_unit_cost(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion coste invalido",
                    "unit": "kg",
                    "current_stock": 1,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                },
            ).json()
            negative = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "unit_cost": -1,
                    "reason": "recepcion_mercancia",
                },
            )
            zero = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "unit_cost": 0,
                    "reason": "recepcion_mercancia",
                },
            )
            non_finite = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "unit_cost": "Infinity",
                    "reason": "recepcion_mercancia",
                },
            )

        self.assertEqual(negative.status_code, 422)
        self.assertEqual(zero.status_code, 422)
        self.assertEqual(non_finite.status_code, 422)

    def test_purchase_intake_rejects_weighted_average_without_previous_cost(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion sin coste previo",
                    "unit": "kg",
                    "current_stock": 3,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                },
            ).json()
            response = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 2,
                    "unit": "kg",
                    "unit_cost": 5,
                    "reason": "recepcion_mercancia",
                    "reference": "ALB-MISSING-WAC",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "weighted_average_cost_missing")
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            movement_count = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.reference == "ALB-MISSING-WAC")
            )

        self.assertEqual(refreshed_item.current_stock, 3)
        self.assertIsNone(refreshed_item.cost)
        self.assertEqual(movement_count, 0)

    def test_purchase_intake_rejects_weighted_average_with_negative_legacy_stock(self):
        with self.SessionTesting() as db:
            item = InventoryItem(
                restaurant_id=1,
                name="Recepcion stock legacy negativo",
                unit="kg",
                current_stock=-1,
                minimum_stock=0,
                ideal_stock=1,
                cost=2,
            )
            db.add(item)
            db.commit()
            item_id = item.id

        with TestClient(app) as client:
            response = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item_id,
                    "quantity": 2,
                    "unit": "kg",
                    "unit_cost": 5,
                    "reason": "recepcion_mercancia",
                    "reference": "ALB-NEGATIVE-WAC",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "weighted_average_negative_stock")
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item_id)
            movement_count = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.reference == "ALB-NEGATIVE-WAC")
            )

        self.assertEqual(refreshed_item.current_stock, -1)
        self.assertEqual(refreshed_item.cost, 2)
        self.assertEqual(movement_count, 0)

    def test_purchase_intake_rejects_item_from_another_restaurant(self):
        with self.SessionTesting() as db:
            restaurant_id = (db.scalar(select(func.max(Restaurant.id))) or 1) + 1
            restaurant = Restaurant(
                id=restaurant_id,
                name=f"Second Restaurant {restaurant_id}",
                slug=f"second-restaurant-{restaurant_id}",
            )
            db.add(restaurant)
            db.flush()
            db.add(
                RestaurantMembership(
                    user_id=1,
                    restaurant_id=restaurant.id,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                )
            )
            db.commit()

        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion restaurante aislado",
                    "unit": "kg",
                    "current_stock": 1,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                },
            ).json()
            response = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": restaurant_id,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "unit_cost": 2,
                    "reason": "recepcion_mercancia",
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "inventory_item_not_found")

    def test_purchase_intake_rolls_back_when_transaction_fails(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion rollback",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                },
            ).json()

            from app.services.inventory_service import create_inventory_movement_record

            def fail_after_movement(db, payload):
                create_inventory_movement_record(db, payload)
                raise RuntimeError("intake failed")

            with patch(
                "app.services.purchase_intake_service.create_inventory_movement_record",
                side_effect=fail_after_movement,
            ):
                response = client.post(
                    "/api/inventory/purchase-intakes",
                    json={
                        "restaurant_id": 1,
                        "inventory_item_id": item["id"],
                        "quantity": 3,
                        "unit": "kg",
                        "reason": "recepcion_mercancia",
                        "reference": "ALB-ROLLBACK",
                    },
                )

        self.assertEqual(response.status_code, 500)
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            intake_movements = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.inventory_item_id == item["id"],
                    InventoryMovement.reference == "ALB-ROLLBACK",
                )
            )

        self.assertEqual(refreshed_item.current_stock, 2)
        self.assertEqual(intake_movements, 0)

    def test_purchase_intake_rolls_back_when_movement_creation_fails(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion rollback movimiento",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                    "cost": 1,
                },
            ).json()

            with patch(
                "app.services.purchase_intake_service.create_inventory_movement_record",
                side_effect=RuntimeError("movement failed"),
            ):
                response = client.post(
                    "/api/inventory/purchase-intakes",
                    json={
                        "restaurant_id": 1,
                        "inventory_item_id": item["id"],
                        "quantity": 3,
                        "unit": "kg",
                        "unit_cost": 2,
                        "reason": "recepcion_mercancia",
                        "reference": "ALB-MOVEMENT-ROLLBACK",
                    },
                )

        self.assertEqual(response.status_code, 500)
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            intake_movements = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.reference == "ALB-MOVEMENT-ROLLBACK")
            )

        self.assertEqual(refreshed_item.current_stock, 2)
        self.assertEqual(refreshed_item.cost, 1)
        self.assertEqual(intake_movements, 0)

    def test_purchase_intake_rolls_back_when_cost_update_fails(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion rollback coste",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                    "cost": 1,
                },
            ).json()

            with patch(
                "app.services.purchase_intake_service.apply_weighted_average_purchase_cost",
                side_effect=RuntimeError("cost update failed"),
            ):
                response = client.post(
                    "/api/inventory/purchase-intakes",
                    json={
                        "restaurant_id": 1,
                        "inventory_item_id": item["id"],
                        "quantity": 3,
                        "unit": "kg",
                        "unit_cost": 2,
                        "reason": "recepcion_mercancia",
                        "reference": "ALB-COST-ROLLBACK",
                    },
                )

        self.assertEqual(response.status_code, 500)
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            intake_movements = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.reference == "ALB-COST-ROLLBACK")
            )

        self.assertEqual(refreshed_item.current_stock, 2)
        self.assertEqual(refreshed_item.cost, 1)
        self.assertEqual(intake_movements, 0)

    def test_purchase_intake_cost_is_compatible_with_production_sales_and_waste(self):
        with TestClient(app) as client:
            ingredient = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Coste compra operativo",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 10,
                },
            ).json()
            produced_item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Producto coste compra",
                    "unit": "unit",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            intake = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 20,
                    "unit": "kg",
                    "unit_cost": 3,
                    "reason": "recepcion_mercancia",
                    "reference": "ALB-COMPAT",
                },
            )
            second_intake = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 10,
                    "unit": "kg",
                    "unit_cost": 6,
                    "reason": "recepcion_mercancia",
                    "reference": "ALB-COMPAT-2",
                },
            )
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 2,
                    "unit": "kg",
                },
            )
            sale = client.post(
                "/api/operations/sales",
                json={"restaurant_id": 1, "dish_id": 1, "quantity": 1, "source": "manual"},
            )
            waste = client.post(
                "/api/inventory/waste-losses",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "reason": "rotura",
                    "loss_category": "breakage",
                },
            )
            production = client.post(
                "/api/inventory/productions",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "produced_inventory_item_id": produced_item["id"],
                    "quantity": 1,
                    "reference": "PROD-COMPAT-PURCHASE",
                },
            )

        self.assertEqual(intake.status_code, 200)
        self.assertEqual(second_intake.status_code, 200)
        self.assertEqual(sale.status_code, 200)
        self.assertEqual(waste.status_code, 200)
        self.assertEqual(production.status_code, 200)
        self.assertEqual(sale.json()["consumed_ingredients"][0]["historical_unit_cost"], 4)
        self.assertEqual(sale.json()["consumed_ingredients"][0]["historical_total_cost"], 8)
        self.assertEqual(waste.json()["historical_unit_cost"], 4)
        self.assertEqual(waste.json()["historical_total_cost"], 4)
        self.assertEqual(production.json()["consumed_ingredients"][0]["historical_unit_cost"], 4)
        self.assertEqual(production.json()["historical_total_cost"], 8)

        with self.SessionTesting() as db:
            first_movement = db.get(InventoryMovement, intake.json()["movement_id"])
            second_movement = db.get(InventoryMovement, second_intake.json()["movement_id"])

        self.assertEqual(first_movement.historical_unit_cost, 3)
        self.assertEqual(first_movement.historical_total_cost, 60)
        self.assertEqual(first_movement.wac_previous_stock, 0)
        self.assertIsNone(first_movement.wac_previous_unit_cost)
        self.assertEqual(first_movement.wac_resulting_unit_cost, 3)
        self.assertEqual(second_movement.historical_unit_cost, 6)
        self.assertEqual(second_movement.historical_total_cost, 60)
        self.assertEqual(second_movement.wac_previous_stock, 20)
        self.assertEqual(second_movement.wac_previous_unit_cost, 3)
        self.assertEqual(second_movement.wac_resulting_unit_cost, 4)

    def test_purchase_intake_weighted_average_supports_decimal_quantities(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recepcion decimales WAC",
                    "unit": "kg",
                    "current_stock": 1.5,
                    "minimum_stock": 0.5,
                    "ideal_stock": 4,
                    "cost": 2.2,
                },
            ).json()
            response = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 0.75,
                    "unit": "kg",
                    "unit_cost": 3.4,
                    "reason": "recepcion_decimal",
                    "reference": "ALB-DECIMAL-WAC",
                },
            )

        self.assertEqual(response.status_code, 200)
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            movement = db.get(InventoryMovement, response.json()["movement_id"])

        self.assertAlmostEqual(refreshed_item.cost, 2.6)
        self.assertEqual(refreshed_item.current_stock, 2.25)
        self.assertEqual(movement.historical_unit_cost, 3.4)
        self.assertEqual(movement.historical_total_cost, 2.55)
        self.assertEqual(movement.wac_previous_stock, 1.5)
        self.assertEqual(movement.wac_previous_unit_cost, 2.2)
        self.assertAlmostEqual(movement.wac_resulting_unit_cost, 2.6)

    def test_costing_uses_purchase_intake_weighted_average_cost(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Costing WAC",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                    "cost": 2,
                },
            ).json()
            client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 2,
                    "unit": "kg",
                    "unit_cost": 6,
                    "reason": "recepcion_costing",
                },
            )
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1.5,
                    "unit": "kg",
                },
            )
            response = client.get("/api/restaurants/1/dishes/1/costing")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["ingredients_breakdown"][0]["unit_cost"], 4)
        self.assertEqual(payload["ingredients_breakdown"][0]["line_cost"], 6)

    def test_purchase_intake_query_lists_domain_reads_with_ingredient_name_and_order(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Query recepcion tomate",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            older = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "unit_cost": 2,
                    "reason": "recepcion",
                    "reference": "QUERY-OLD",
                    "received_at": "2026-01-01T10:00:00",
                },
            ).json()
            newer = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "unit_cost": 4,
                    "reason": "recepcion",
                    "reference": "QUERY-NEW",
                    "received_at": "2026-01-02T10:00:00",
                },
            ).json()
            response = client.get("/api/inventory/purchase-intakes?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        ids = [entry["movement_id"] for entry in payload]
        self.assertLess(ids.index(newer["movement_id"]), ids.index(older["movement_id"]))
        intake = next(entry for entry in payload if entry["reference"] == "QUERY-NEW")
        self.assertEqual(intake["id"], newer["movement_id"])
        self.assertEqual(intake["ingredient_name"], "Query recepcion tomate")
        self.assertEqual(intake["purchase_unit_cost"], 4)
        self.assertEqual(intake["purchase_total_cost"], 4)
        self.assertEqual(intake["previous_stock"], 1)
        self.assertEqual(intake["previous_unit_cost"], 2)
        self.assertEqual(intake["resulting_unit_cost"], 3)
        self.assertTrue(intake["is_valued"])

    def test_purchase_intake_query_filters_restaurant_item_reference_dates_and_value_state(self):
        with self.SessionTesting() as db:
            restaurant = Restaurant(name="Query Tenant", slug="query-tenant")
            db.add(restaurant)
            db.flush()
            db.add(
                RestaurantMembership(
                    user_id=1,
                    restaurant_id=restaurant.id,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                )
            )
            db.commit()
            restaurant_id = restaurant.id

        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Query filtros",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            other_item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Query filtros otro",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            tenant_item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": restaurant_id,
                    "name": "Query filtros tenant",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "unit_cost": 2,
                    "reason": "recepcion",
                    "reference": "FILTER-MATCH",
                    "received_at": "2026-02-10T12:00:00",
                },
            )
            client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": other_item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "reason": "recepcion",
                    "reference": "FILTER-UNVALUED",
                    "received_at": "2026-02-11T12:00:00",
                },
            )
            client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": restaurant_id,
                    "inventory_item_id": tenant_item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "unit_cost": 3,
                    "reason": "recepcion",
                    "reference": "FILTER-TENANT",
                    "received_at": "2026-02-10T12:00:00",
                },
            )
            by_restaurant = client.get("/api/inventory/purchase-intakes?restaurant_id=1")
            by_item = client.get(f"/api/inventory/purchase-intakes?restaurant_id=1&inventory_item_id={item['id']}")
            by_reference = client.get("/api/inventory/purchase-intakes?restaurant_id=1&reference=FILTER-MATCH")
            by_start = client.get("/api/inventory/purchase-intakes?restaurant_id=1&start_date=2026-02-11T12:00:00")
            by_end = client.get("/api/inventory/purchase-intakes?restaurant_id=1&end_date=2026-02-10T12:00:00")
            valued = client.get("/api/inventory/purchase-intakes?restaurant_id=1&is_valued=true")
            unvalued = client.get("/api/inventory/purchase-intakes?restaurant_id=1&is_valued=false")

        self.assertEqual(by_restaurant.status_code, 200)
        self.assertNotIn("FILTER-TENANT", [entry["reference"] for entry in by_restaurant.json()])
        self.assertEqual([entry["reference"] for entry in by_item.json()], ["FILTER-MATCH"])
        self.assertEqual([entry["reference"] for entry in by_reference.json()], ["FILTER-MATCH"])
        self.assertIn("FILTER-UNVALUED", [entry["reference"] for entry in by_start.json()])
        self.assertIn("FILTER-MATCH", [entry["reference"] for entry in by_end.json()])
        self.assertIn("FILTER-MATCH", [entry["reference"] for entry in valued.json()])
        self.assertNotIn("FILTER-UNVALUED", [entry["reference"] for entry in valued.json()])
        self.assertIn("FILTER-UNVALUED", [entry["reference"] for entry in unvalued.json()])

    def test_purchase_intake_query_excludes_non_purchase_in_movements_and_keeps_legacy_unvalued(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Query legacy",
                    "unit": "kg",
                    "current_stock": 3,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                    "cost": 2,
                },
            ).json()
            client.post(
                "/api/inventory/movements",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "movement_type": "IN",
                    "quantity": 1,
                    "unit": "kg",
                    "origin_type": "manual_count",
                    "reference": "NOT-PURCHASE",
                },
            )

        with self.SessionTesting() as db:
            db.add(
                InventoryMovement(
                    restaurant_id=1,
                    inventory_item_id=item["id"],
                    movement_type="IN",
                    quantity=2,
                    unit="kg",
                    reason="legacy_recepcion",
                    origin_type="purchase_intake",
                    reference="LEGACY-PURCHASE",
                    historical_unit_cost=3,
                    created_at=datetime(2026, 3, 1, 12, 0, 0),
                )
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/inventory/purchase-intakes?restaurant_id=1")

        references = [entry["reference"] for entry in response.json()]
        self.assertIn("LEGACY-PURCHASE", references)
        self.assertNotIn("NOT-PURCHASE", references)
        legacy = next(entry for entry in response.json() if entry["reference"] == "LEGACY-PURCHASE")
        self.assertFalse(legacy["is_valued"])
        self.assertEqual(legacy["purchase_unit_cost"], 3)
        self.assertIsNone(legacy["purchase_total_cost"])

    def test_purchase_intake_query_applies_limit_and_stable_tie_order_without_modifying_ledger(self):
        same_time = "2026-04-01T12:00:00"
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Query limite",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            first = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "unit_cost": 1,
                    "reason": "recepcion",
                    "reference": "LIMIT-1",
                    "received_at": same_time,
                },
            ).json()
            second = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "unit_cost": 3,
                    "reason": "recepcion",
                    "reference": "LIMIT-2",
                    "received_at": same_time,
                },
            ).json()
            third = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "unit_cost": 5,
                    "reason": "recepcion",
                    "reference": "LIMIT-3",
                    "received_at": same_time,
                },
            ).json()

        with self.SessionTesting() as db:
            before_count = db.scalar(select(func.count()).select_from(InventoryMovement))

        with TestClient(app) as client:
            response = client.get("/api/inventory/purchase-intakes?restaurant_id=1&limit=2")
            too_large = client.get("/api/inventory/purchase-intakes?restaurant_id=1&limit=501")

        with self.SessionTesting() as db:
            after_count = db.scalar(select(func.count()).select_from(InventoryMovement))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(too_large.status_code, 422)
        payload = response.json()
        self.assertEqual(len(payload), 2)
        self.assertEqual([entry["movement_id"] for entry in payload[:2]], [third["movement_id"], second["movement_id"]])
        self.assertGreater(second["movement_id"], first["movement_id"])
        self.assertEqual(before_count, after_count)

    def test_purchase_intake_query_preserves_post_endpoint_compatibility(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Query compat post",
                    "unit": "unit",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 3,
                },
            ).json()
            created = client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 2,
                    "unit": "unit",
                    "reason": "compra_directa",
                    "reference": "POST-COMPAT",
                },
            )
            listed = client.get("/api/inventory/purchase-intakes?restaurant_id=1&reference=POST-COMPAT")

        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["current_stock"], 2)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        self.assertFalse(listed.json()[0]["is_valued"])

    def test_inventory_ledger_audit_clean_ledger_has_no_findings(self):
        with TestClient(app) as client:
            client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Audit limpio",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 0,
                    "ideal_stock": 1,
                },
            )
            response = client.get("/api/inventory/ledger-audit?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["total_issues"], 0)
        self.assertEqual(payload["summary"]["movements_audited"], 0)
        self.assertEqual(payload["summary"]["inventory_items_audited"], 1)
        self.assertEqual(payload["issues"], [])

    def test_inventory_ledger_audit_detects_origin_cost_total_wac_and_legacy_issues(self):
        with self.SessionTesting() as db:
            item = InventoryItem(
                restaurant_id=1,
                name="Audit inconsistencias",
                unit="kg",
                current_stock=5,
                minimum_stock=0,
                ideal_stock=1,
                cost=2,
            )
            db.add(item)
            db.flush()
            db.add_all(
                [
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="OUT",
                        quantity=1,
                        unit="kg",
                        reason="sale",
                        origin_type="purchase_intake",
                        historical_unit_cost=2,
                        historical_total_cost=2,
                        created_at=datetime(2026, 5, 1, 10, 0, 0),
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="WASTE",
                        quantity=1,
                        unit="kg",
                        reason="rotura",
                        origin_type="inventory_waste_loss",
                        created_at=datetime(2026, 5, 1, 11, 0, 0),
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="OUT",
                        quantity=2,
                        unit="kg",
                        reason="sale",
                        origin_type="sale",
                        historical_unit_cost=3,
                        historical_total_cost=10,
                        created_at=datetime(2026, 5, 1, 12, 0, 0),
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="IN",
                        quantity=2,
                        unit="kg",
                        reason="recepcion",
                        origin_type="purchase_intake",
                        historical_unit_cost=4,
                        historical_total_cost=8,
                        wac_previous_stock=2,
                        wac_resulting_unit_cost=4,
                        created_at=datetime(2026, 5, 1, 13, 0, 0),
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="IN",
                        quantity=1,
                        unit="kg",
                        reason="legacy",
                        created_at=datetime(2026, 5, 1, 14, 0, 0),
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="ADJUSTMENT",
                        quantity=1,
                        unit="kg",
                        reason="legacy_adjustment",
                        created_at=datetime(2026, 5, 1, 15, 0, 0),
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/inventory/ledger-audit?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        codes = [issue["code"] for issue in payload["issues"]]
        self.assertIn("movement_origin_mismatch", codes)
        self.assertIn("historical_cost_missing", codes)
        self.assertIn("waste_category_missing", codes)
        self.assertIn("historical_total_mismatch", codes)
        self.assertIn("wac_trace_incomplete", codes)
        self.assertIn("legacy_ambiguous_movement", codes)
        self.assertIn("legacy_adjustment_movement", codes)
        self.assertIn("stock_ledger_mismatch", codes)
        self.assertGreaterEqual(payload["summary"]["issues_by_severity"]["error"], 1)
        self.assertGreaterEqual(payload["summary"]["issues_by_code"]["historical_cost_missing"], 1)
        self.assertEqual(payload["issues"][0]["severity"], "critical")
        self.assertEqual(payload["issues"][0]["ingredient_name"], "Audit inconsistencias")

    def test_inventory_ledger_audit_accepts_valid_purchase_wac_waste_and_production(self):
        with TestClient(app) as client:
            ingredient = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Audit valido ingrediente",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 0,
                    "ideal_stock": 10,
                },
            ).json()
            product = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Audit valido producto",
                    "unit": "unit",
                    "current_stock": 0,
                    "minimum_stock": 0,
                    "ideal_stock": 5,
                },
            ).json()
            client.post(
                "/api/inventory/purchase-intakes",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 10,
                    "unit": "kg",
                    "unit_cost": 2,
                    "reason": "recepcion",
                },
            )
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 2,
                    "unit": "kg",
                },
            )
            production = client.post(
                "/api/inventory/productions",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "produced_inventory_item_id": product["id"],
                    "quantity": 1,
                },
            )
            waste = client.post(
                "/api/inventory/waste-losses",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "reason": "rotura",
                    "loss_category": "breakage",
                },
            )
            response = client.get("/api/inventory/ledger-audit?restaurant_id=1")

        self.assertEqual(production.status_code, 200)
        self.assertEqual(waste.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["issues"], [])

    def test_inventory_ledger_audit_detects_wac_math_and_negative_previous_stock(self):
        with self.SessionTesting() as db:
            item = InventoryItem(
                restaurant_id=1,
                name="Audit WAC matematico",
                unit="kg",
                current_stock=3,
                minimum_stock=0,
                ideal_stock=5,
                cost=2,
            )
            db.add(item)
            db.flush()
            db.add_all(
                [
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="IN",
                        quantity=1,
                        unit="kg",
                        reason="recepcion",
                        origin_type="purchase_intake",
                        historical_unit_cost=4,
                        historical_total_cost=4,
                        wac_previous_stock=2,
                        wac_previous_unit_cost=2,
                        wac_resulting_unit_cost=9,
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="IN",
                        quantity=1,
                        unit="kg",
                        reason="recepcion",
                        origin_type="purchase_intake",
                        historical_unit_cost=4,
                        historical_total_cost=4,
                        wac_previous_stock=-1,
                        wac_previous_unit_cost=2,
                        wac_resulting_unit_cost=4,
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/inventory/ledger-audit?restaurant_id=1&code=wac_result_mismatch")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["issues"]), 2)
        self.assertTrue(all(issue["code"] == "wac_result_mismatch" for issue in payload["issues"]))

    def test_inventory_ledger_audit_detects_production_group_inconsistencies(self):
        with self.SessionTesting() as db:
            other_restaurant = Restaurant(name="Audit Production Tenant", slug="audit-production-tenant")
            db.add(other_restaurant)
            db.flush()
            db.add(
                RestaurantMembership(
                    user_id=1,
                    restaurant_id=other_restaurant.id,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                )
            )
            item = InventoryItem(restaurant_id=1, name="Audit produccion item", unit="kg", current_stock=0)
            other_item = InventoryItem(restaurant_id=other_restaurant.id, name="Audit produccion otro", unit="kg", current_stock=0)
            db.add_all([item, other_item])
            db.flush()
            db.add_all(
                [
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="PRODUCTION_OUTPUT",
                        quantity=1,
                        unit="kg",
                        reason="production_output",
                        origin_type="inventory_production",
                        origin_id="prod:no-consume",
                        historical_unit_cost=2,
                        historical_total_cost=2,
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="PRODUCTION_CONSUME",
                        quantity=1,
                        unit="kg",
                        reason="production_consumption",
                        origin_type="inventory_production",
                        origin_id="prod:no-output",
                        historical_unit_cost=2,
                        historical_total_cost=2,
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="PRODUCTION_CONSUME",
                        quantity=1,
                        unit="kg",
                        reason="production_consumption",
                        origin_type="inventory_production",
                        origin_id="prod:two-output",
                        historical_unit_cost=2,
                        historical_total_cost=2,
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="PRODUCTION_OUTPUT",
                        quantity=1,
                        unit="kg",
                        reason="production_output",
                        origin_type="inventory_production",
                        origin_id="prod:two-output",
                        historical_unit_cost=2,
                        historical_total_cost=2,
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="PRODUCTION_OUTPUT",
                        quantity=1,
                        unit="kg",
                        reason="production_output",
                        origin_type="inventory_production",
                        origin_id="prod:two-output",
                        historical_unit_cost=2,
                        historical_total_cost=2,
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="PRODUCTION_CONSUME",
                        quantity=1,
                        unit="kg",
                        reason="production_consumption",
                        origin_type="inventory_production",
                        origin_id="prod:tenant-mix",
                        historical_unit_cost=2,
                        historical_total_cost=2,
                    ),
                    InventoryMovement(
                        restaurant_id=other_restaurant.id,
                        inventory_item_id=other_item.id,
                        movement_type="PRODUCTION_OUTPUT",
                        quantity=1,
                        unit="kg",
                        reason="production_output",
                        origin_type="inventory_production",
                        origin_id="prod:tenant-mix",
                        historical_unit_cost=2,
                        historical_total_cost=2,
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/inventory/ledger-audit?code=production_group_incomplete")
            tenant_mix = client.get("/api/inventory/ledger-audit?code=production_group_restaurant_mismatch")

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["issues"]), 3)
        self.assertEqual(tenant_mix.status_code, 200)
        self.assertEqual(tenant_mix.json()["issues"], [])

    def test_inventory_ledger_audit_filters_limits_orders_and_does_not_modify_data(self):
        with self.SessionTesting() as db:
            restaurant = Restaurant(name="Audit Filter Tenant", slug="audit-filter-tenant")
            db.add(restaurant)
            db.flush()
            db.add(
                RestaurantMembership(
                    user_id=1,
                    restaurant_id=restaurant.id,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                )
            )
            item = InventoryItem(restaurant_id=1, name="Audit filtros", unit="kg", current_stock=0)
            tenant_item = InventoryItem(restaurant_id=restaurant.id, name="Audit filtros tenant", unit="kg", current_stock=0)
            db.add_all([item, tenant_item])
            db.flush()
            db.add_all(
                [
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="OUT",
                        quantity=1,
                        unit="kg",
                        reason="sale",
                        origin_type="sale",
                        created_at=datetime(2026, 6, 1, 10, 0, 0),
                    ),
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=item.id,
                        movement_type="IN",
                        quantity=1,
                        unit="kg",
                        reason="legacy",
                        created_at=datetime(2026, 6, 1, 11, 0, 0),
                    ),
                    InventoryMovement(
                        restaurant_id=restaurant.id,
                        inventory_item_id=tenant_item.id,
                        movement_type="OUT",
                        quantity=1,
                        unit="kg",
                        reason="sale",
                        origin_type="sale",
                    ),
                ]
            )
            db.commit()
            item_id = item.id
            restaurant_id = restaurant.id
            before_count = db.scalar(select(func.count()).select_from(InventoryMovement))

        with TestClient(app) as client:
            severity = client.get("/api/inventory/ledger-audit?restaurant_id=1&severity=error")
            code = client.get("/api/inventory/ledger-audit?restaurant_id=1&code=legacy_ambiguous_movement")
            ingredient = client.get(f"/api/inventory/ledger-audit?restaurant_id=1&inventory_item_id={item_id}")
            tenant = client.get(f"/api/inventory/ledger-audit?restaurant_id={restaurant_id}")
            limited = client.get("/api/inventory/ledger-audit?restaurant_id=1&limit=1")
            too_large = client.get("/api/inventory/ledger-audit?restaurant_id=1&limit=501")

        with self.SessionTesting() as db:
            after_count = db.scalar(select(func.count()).select_from(InventoryMovement))

        self.assertEqual(severity.status_code, 200)
        self.assertTrue(all(issue["severity"] == "error" for issue in severity.json()["issues"]))
        self.assertEqual([issue["code"] for issue in code.json()["issues"]], ["legacy_ambiguous_movement"])
        self.assertTrue(all(issue["inventory_item_id"] == item_id for issue in ingredient.json()["issues"]))
        self.assertNotEqual(tenant.json()["restaurant_id"], 1)
        self.assertEqual(len(limited.json()["issues"]), 1)
        self.assertEqual(too_large.status_code, 422)
        self.assertEqual(before_count, after_count)
        severities = [issue["severity"] for issue in ingredient.json()["issues"]]
        self.assertEqual(severities, sorted(severities, key=lambda value: {"critical": 0, "error": 1, "warning": 2, "info": 3}[value]))

    def test_inventory_adjustment_positive_updates_stock_and_creates_movement(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Ajuste positivo",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            response = client.post(
                "/api/inventory/adjustments",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "stock_difference": 1.5,
                    "unit": "kg",
                    "reason": "conteo_fisico",
                    "reference": "COUNT-1",
                    "created_by": "ops@example.com",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["current_stock"], 3.5)
        self.assertEqual(payload["movement_type"], "ADJUSTMENT_POSITIVE")
        self.assertEqual(payload["reference"], "COUNT-1")

        with self.SessionTesting() as db:
            movement = db.get(InventoryMovement, payload["movement_id"])

        self.assertEqual(movement.quantity, 1.5)
        self.assertEqual(movement.reason, "conteo_fisico")
        self.assertEqual(movement.origin_type, "inventory_adjustment")
        self.assertEqual(movement.created_by, "ops@example.com")

    def test_inventory_adjustment_negative_updates_stock_and_creates_movement(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Ajuste negativo",
                    "unit": "unit",
                    "current_stock": 5,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                    "cost": 4,
                },
            ).json()
            response = client.post(
                "/api/inventory/adjustments",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "stock_difference": -2,
                    "unit": "unit",
                    "reason": "conteo_fisico",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["current_stock"], 3)
        self.assertEqual(payload["movement_type"], "ADJUSTMENT_NEGATIVE")

        with self.SessionTesting() as db:
            movement = db.get(InventoryMovement, payload["movement_id"])

        self.assertEqual(movement.quantity, 2)
        self.assertEqual(movement.movement_type, "ADJUSTMENT_NEGATIVE")

    def test_inventory_adjustment_rejects_missing_reason(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Ajuste motivo",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            response = client.post(
                "/api/inventory/adjustments",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "stock_difference": 1,
                    "unit": "kg",
                    "reason": "   ",
                },
            )

        self.assertEqual(response.status_code, 422)

    def test_inventory_adjustment_rejects_zero_difference(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Ajuste cero",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            response = client.post(
                "/api/inventory/adjustments",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "stock_difference": 0,
                    "unit": "kg",
                    "reason": "conteo_fisico",
                },
            )

        self.assertEqual(response.status_code, 422)

    def test_inventory_adjustment_rolls_back_when_transaction_fails(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Ajuste rollback",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()

            from app.services.inventory_service import create_inventory_movement_record

            def fail_after_movement(db, payload):
                create_inventory_movement_record(db, payload)
                raise RuntimeError("adjustment failed")

            with patch(
                "app.services.inventory_adjustment_service.create_inventory_movement_record",
                side_effect=fail_after_movement,
            ):
                response = client.post(
                    "/api/inventory/adjustments",
                    json={
                        "restaurant_id": 1,
                        "inventory_item_id": item["id"],
                        "stock_difference": 4,
                        "unit": "kg",
                        "reason": "conteo_fisico",
                        "reference": "ADJ-ROLLBACK",
                    },
                )

        self.assertEqual(response.status_code, 500)
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            adjustment_movements = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.inventory_item_id == item["id"],
                    InventoryMovement.reference == "ADJ-ROLLBACK",
                )
            )

        self.assertEqual(refreshed_item.current_stock, 2)
        self.assertEqual(adjustment_movements, 0)

    def test_inventory_reconciliation_reports_no_differences(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Conciliacion ok",
                    "unit": "kg",
                    "current_stock": 4,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                },
            ).json()
            client.post(
                "/api/inventory/adjustments",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "stock_difference": -1,
                    "unit": "kg",
                    "reason": "conteo_fisico",
                },
            )
            response = client.get("/api/inventory/reconciliation?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        line = next(entry for entry in payload["items"] if entry["inventory_item_id"] == item["id"])
        self.assertEqual(line["operational_stock"], 3)
        self.assertEqual(line["expected_stock"], 3)
        self.assertEqual(line["difference"], 0)
        self.assertEqual(line["status"], "ok")

    def test_inventory_reconciliation_reports_differences_without_mutating_stock(self):
        with self.SessionTesting() as db:
            item = InventoryItem(
                restaurant_id=1,
                name="Conciliacion discrepante",
                unit="kg",
                current_stock=10,
                minimum_stock=1,
                ideal_stock=12,
            )
            db.add(item)
            db.flush()
            db.add(
                InventoryMovement(
                    restaurant_id=1,
                    inventory_item_id=item.id,
                    movement_type="IN",
                    quantity=7,
                    unit="kg",
                    reason="initial_stock",
                )
            )
            db.commit()
            item_id = item.id

        with TestClient(app) as client:
            response = client.get("/api/inventory/reconciliation?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        line = next(entry for entry in response.json()["items"] if entry["inventory_item_id"] == item_id)
        self.assertEqual(line["operational_stock"], 10)
        self.assertEqual(line["expected_stock"], 7)
        self.assertEqual(line["difference"], 3)
        self.assertEqual(line["status"], "discrepant")

        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item_id)

        self.assertEqual(refreshed_item.current_stock, 10)

    def test_inventory_waste_loss_decrements_stock_and_creates_waste_movement(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Merma tomate",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                    "cost": 4,
                },
            ).json()
            response = client.post(
                "/api/inventory/waste-losses",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1.25,
                    "unit": "kg",
                    "reason": "camara fuera de temperatura",
                    "loss_category": "spoilage",
                    "reference": "INC-FOOD-1",
                    "created_by": "chef@example.com",
                },
            )
            listed = client.get("/api/inventory/waste-losses?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["current_stock"], 3.75)
        self.assertEqual(payload["loss_category"], "spoilage")
        self.assertEqual(payload["reference"], "INC-FOOD-1")
        self.assertEqual(payload["historical_unit_cost"], 4)
        self.assertEqual(payload["historical_total_cost"], 5)
        self.assertTrue(any(entry["movement_id"] == payload["movement_id"] for entry in listed.json()))

        with self.SessionTesting() as db:
            movement = db.get(InventoryMovement, payload["movement_id"])

        self.assertEqual(movement.movement_type, "WASTE")
        self.assertEqual(movement.quantity, 1.25)
        self.assertEqual(movement.loss_category, "spoilage")
        self.assertEqual(movement.historical_unit_cost, 4)
        self.assertEqual(movement.historical_total_cost, 5)
        self.assertEqual(movement.origin_type, "inventory_waste_loss")
        self.assertEqual(movement.created_by, "chef@example.com")

    def test_inventory_waste_loss_rejects_invalid_category(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Merma categoria",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                },
            ).json()
            response = client.post(
                "/api/inventory/waste-losses",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "reason": "conteo",
                    "loss_category": "bad_category",
                },
            )

        self.assertEqual(response.status_code, 422)

    def test_inventory_waste_loss_preserves_historical_cost_after_cost_changes(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Merma historico coste",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                    "cost": 6,
                },
            ).json()
            waste = client.post(
                "/api/inventory/waste-losses",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1.5,
                    "unit": "kg",
                    "reason": "caducidad",
                    "loss_category": "expiration",
                },
            ).json()
            client.patch(f"/api/inventory/items/{item['id']}", json={"cost": 12})
            listed = client.get("/api/inventory/waste-losses?restaurant_id=1").json()

        self.assertEqual(waste["historical_unit_cost"], 6)
        self.assertEqual(waste["historical_total_cost"], 9)
        persisted = next(entry for entry in listed if entry["movement_id"] == waste["movement_id"])
        self.assertEqual(persisted["historical_unit_cost"], 6)
        self.assertEqual(persisted["historical_total_cost"], 9)

    def test_inventory_waste_loss_rolls_back_when_cost_is_missing(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Merma sin coste",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                },
            ).json()
            response = client.post(
                "/api/inventory/waste-losses",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "reason": "caducidad",
                    "loss_category": "expiration",
                    "reference": "WASTE-MISSING-COST",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "waste_cost_missing")
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            waste_movements = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(InventoryMovement.reference == "WASTE-MISSING-COST")
            )

        self.assertEqual(refreshed_item.current_stock, 5)
        self.assertEqual(waste_movements, 0)

    def test_inventory_waste_loss_rejects_missing_reason(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Merma motivo",
                    "unit": "kg",
                    "current_stock": 2,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                },
            ).json()
            response = client.post(
                "/api/inventory/waste-losses",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                    "reason": "   ",
                    "loss_category": "breakage",
                },
            )

        self.assertEqual(response.status_code, 422)

    def test_inventory_waste_loss_rejects_negative_stock(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Merma stock negativo",
                    "unit": "kg",
                    "current_stock": 1,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                    "cost": 2,
                },
            ).json()
            response = client.post(
                "/api/inventory/waste-losses",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 2,
                    "unit": "kg",
                    "reason": "caducado",
                    "loss_category": "expiration",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "inventory_stock_negative")

    def test_inventory_waste_loss_rolls_back_when_transaction_fails(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Merma rollback",
                    "unit": "kg",
                    "current_stock": 3,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                    "cost": 2,
                },
            ).json()

            from app.services.inventory_service import create_inventory_movement_record

            def fail_after_movement(db, payload):
                create_inventory_movement_record(db, payload)
                raise RuntimeError("waste failed")

            with patch(
                "app.services.inventory_waste_service.create_inventory_movement_record",
                side_effect=fail_after_movement,
            ):
                response = client.post(
                    "/api/inventory/waste-losses",
                    json={
                        "restaurant_id": 1,
                        "inventory_item_id": item["id"],
                        "quantity": 1,
                        "unit": "kg",
                        "reason": "rotura",
                        "loss_category": "breakage",
                        "reference": "WASTE-ROLLBACK",
                    },
                )

        self.assertEqual(response.status_code, 500)
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            waste_movements = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.inventory_item_id == item["id"],
                    InventoryMovement.reference == "WASTE-ROLLBACK",
                )
            )

        self.assertEqual(refreshed_item.current_stock, 3)
        self.assertEqual(waste_movements, 0)

    def test_inventory_waste_loss_is_consumption_for_planning(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Merma planning",
                    "unit": "kg",
                    "current_stock": 6,
                    "minimum_stock": 1,
                    "ideal_stock": 10,
                    "cost": 2,
                },
            ).json()
            client.post(
                "/api/inventory/waste-losses",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 2,
                    "unit": "kg",
                    "reason": "caducidad",
                    "loss_category": "expiration",
                },
            )
            response = client.get(f"/api/inventory/planning/items/{item['id']}?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["has_consumption_data"])
        self.assertEqual(payload["historical_consumption"], 2)
        self.assertEqual(payload["current_stock"], 4)

    def test_inventory_production_consumes_ingredients_and_outputs_product(self):
        with TestClient(app) as client:
            ingredient = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Harina produccion",
                    "unit": "kg",
                    "current_stock": 10,
                    "minimum_stock": 1,
                    "ideal_stock": 12,
                    "cost": 3,
                },
            ).json()
            produced_item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Masa producida",
                    "unit": "unit",
                    "current_stock": 1,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 2,
                    "unit": "kg",
                },
            )
            response = client.post(
                "/api/inventory/productions",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "produced_inventory_item_id": produced_item["id"],
                    "quantity": 2,
                    "reference": "PROD-1",
                    "created_by": "kitchen@example.com",
                },
            )
            refreshed = client.get("/api/inventory/items?restaurant_id=1").json()
            listed = client.get("/api/inventory/productions?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["produced_inventory_item_id"], produced_item["id"])
        self.assertEqual(payload["current_stock"], 3)
        self.assertEqual(payload["reference"], "PROD-1")
        self.assertEqual(payload["created_by"], "kitchen@example.com")
        self.assertEqual(payload["consumed_ingredients"][0]["quantity"], 4)
        self.assertEqual(payload["consumed_ingredients"][0]["historical_unit_cost"], 3)
        self.assertEqual(payload["consumed_ingredients"][0]["historical_total_cost"], 12)
        self.assertEqual(payload["historical_unit_cost"], 6)
        self.assertEqual(payload["historical_total_cost"], 12)
        self.assertTrue(any(entry["output_movement_id"] == payload["output_movement_id"] for entry in listed.json()))

        flour = next(item for item in refreshed if item["id"] == ingredient["id"])
        dough = next(item for item in refreshed if item["id"] == produced_item["id"])
        self.assertEqual(flour["current_stock"], 6)
        self.assertEqual(dough["current_stock"], 3)

        with self.SessionTesting() as db:
            movements = list(
                db.scalars(
                    select(InventoryMovement)
                    .where(InventoryMovement.origin_id == payload["origin_id"])
                    .order_by(InventoryMovement.id)
                ).all()
            )

        self.assertEqual([movement.movement_type for movement in movements], ["PRODUCTION_CONSUME", "PRODUCTION_OUTPUT"])
        self.assertEqual(movements[0].quantity, 4)
        self.assertEqual(movements[0].historical_unit_cost, 3)
        self.assertEqual(movements[0].historical_total_cost, 12)
        self.assertEqual(movements[1].quantity, 2)
        self.assertEqual(movements[1].inventory_item_id, produced_item["id"])
        self.assertEqual(movements[1].historical_unit_cost, 6)
        self.assertEqual(movements[1].historical_total_cost, 12)

    def test_inventory_production_rejects_missing_recipe(self):
        with TestClient(app) as client:
            produced_item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Producto sin receta produccion",
                    "unit": "unit",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                },
            ).json()
            response = client.post(
                "/api/inventory/productions",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "produced_inventory_item_id": produced_item["id"],
                    "quantity": 1,
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "recipe_empty")

    def test_inventory_production_preserves_historical_cost_after_ingredient_cost_changes(self):
        with TestClient(app) as client:
            ingredient = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Historico coste produccion",
                    "unit": "kg",
                    "current_stock": 10,
                    "minimum_stock": 1,
                    "ideal_stock": 12,
                    "cost": 4,
                },
            ).json()
            produced_item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Historico salida produccion",
                    "unit": "unit",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 1.5,
                    "unit": "kg",
                },
            )
            production = client.post(
                "/api/inventory/productions",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "produced_inventory_item_id": produced_item["id"],
                    "quantity": 2,
                    "reference": "PROD-COST-HISTORY",
                },
            ).json()
            client.patch(f"/api/inventory/items/{ingredient['id']}", json={"cost": 9})
            listed = client.get("/api/inventory/productions?restaurant_id=1").json()

        self.assertEqual(production["historical_total_cost"], 12)
        persisted = next(entry for entry in listed if entry["output_movement_id"] == production["output_movement_id"])
        self.assertEqual(persisted["historical_total_cost"], 12)
        self.assertEqual(persisted["historical_unit_cost"], 6)
        self.assertEqual(persisted["consumed_ingredients"][0]["historical_unit_cost"], 4)
        self.assertEqual(persisted["consumed_ingredients"][0]["historical_total_cost"], 12)

        with self.SessionTesting() as db:
            output_movement = db.get(InventoryMovement, production["output_movement_id"])

        self.assertEqual(output_movement.historical_total_cost, 12)
        self.assertEqual(output_movement.historical_unit_cost, 6)

    def test_inventory_production_rolls_back_when_cost_is_missing(self):
        with TestClient(app) as client:
            ingredient = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Sin coste produccion",
                    "unit": "kg",
                    "current_stock": 10,
                    "minimum_stock": 1,
                    "ideal_stock": 12,
                },
            ).json()
            produced_item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Salida sin coste produccion",
                    "unit": "unit",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 2,
                    "unit": "kg",
                },
            )
            response = client.post(
                "/api/inventory/productions",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "produced_inventory_item_id": produced_item["id"],
                    "quantity": 2,
                    "reference": "PROD-MISSING-COST",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "production_cost_missing")

        with self.SessionTesting() as db:
            refreshed_ingredient = db.get(InventoryItem, ingredient["id"])
            refreshed_product = db.get(InventoryItem, produced_item["id"])
            production_movements = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.reference == "PROD-MISSING-COST",
                    InventoryMovement.movement_type.in_(["PRODUCTION_CONSUME", "PRODUCTION_OUTPUT"]),
                )
            )

        self.assertEqual(refreshed_ingredient.current_stock, 10)
        self.assertEqual(refreshed_product.current_stock, 0)
        self.assertEqual(production_movements, 0)

    def test_inventory_production_rejects_insufficient_stock(self):
        with TestClient(app) as client:
            ingredient = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Stock corto produccion",
                    "unit": "kg",
                    "current_stock": 1,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                    "cost": 2,
                },
            ).json()
            produced_item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Producto stock corto",
                    "unit": "unit",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 2,
                    "unit": "kg",
                },
            )
            response = client.post(
                "/api/inventory/productions",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "produced_inventory_item_id": produced_item["id"],
                    "quantity": 1,
                    "reference": "PROD-NOSTOCK",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "inventory_stock_negative")

        with self.SessionTesting() as db:
            refreshed_ingredient = db.get(InventoryItem, ingredient["id"])
            refreshed_product = db.get(InventoryItem, produced_item["id"])
            production_movements = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.reference == "PROD-NOSTOCK",
                    InventoryMovement.movement_type.in_(["PRODUCTION_CONSUME", "PRODUCTION_OUTPUT"]),
                )
            )

        self.assertEqual(refreshed_ingredient.current_stock, 1)
        self.assertEqual(refreshed_product.current_stock, 0)
        self.assertEqual(production_movements, 0)

    def test_inventory_production_rolls_back_when_output_fails(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            ingredient = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Rollback produccion ingrediente",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                    "cost": 2,
                },
            ).json()
            produced_item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Rollback produccion producto",
                    "unit": "unit",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 2,
                    "unit": "kg",
                },
            )

            from app.services.inventory_service import create_inventory_movement_record

            call_count = 0

            def fail_on_output(db, payload):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise RuntimeError("production output failed")
                return create_inventory_movement_record(db, payload)

            with patch(
                "app.services.production_service.create_inventory_movement_record",
                side_effect=fail_on_output,
            ):
                response = client.post(
                    "/api/inventory/productions",
                    json={
                        "restaurant_id": 1,
                        "dish_id": 1,
                        "produced_inventory_item_id": produced_item["id"],
                        "quantity": 1,
                        "reference": "PROD-ROLLBACK",
                    },
                )

        self.assertEqual(response.status_code, 500)
        with self.SessionTesting() as db:
            refreshed_ingredient = db.get(InventoryItem, ingredient["id"])
            refreshed_product = db.get(InventoryItem, produced_item["id"])
            production_movements = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.reference == "PROD-ROLLBACK",
                    InventoryMovement.movement_type.in_(["PRODUCTION_CONSUME", "PRODUCTION_OUTPUT"]),
                )
            )

        self.assertEqual(refreshed_ingredient.current_stock, 5)
        self.assertEqual(refreshed_product.current_stock, 0)
        self.assertEqual(production_movements, 0)

    def test_inventory_production_consumption_is_visible_to_planning(self):
        with TestClient(app) as client:
            ingredient = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Planning produccion ingrediente",
                    "unit": "kg",
                    "current_stock": 6,
                    "minimum_stock": 1,
                    "ideal_stock": 10,
                    "cost": 2,
                },
            ).json()
            produced_item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Planning produccion salida",
                    "unit": "unit",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": ingredient["id"],
                    "quantity": 2,
                    "unit": "kg",
                },
            )
            client.post(
                "/api/inventory/productions",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "produced_inventory_item_id": produced_item["id"],
                    "quantity": 1,
                },
            )
            response = client.get(f"/api/inventory/planning/items/{ingredient['id']}?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["has_consumption_data"])
        self.assertEqual(payload["historical_consumption"], 2)
        self.assertEqual(payload["current_stock"], 4)

    def test_dish_ingredient_can_be_created(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Masa test",
                    "unit": "g",
                    "current_stock": 1000,
                    "minimum_stock": 300,
                    "ideal_stock": 1500,
                },
            ).json()
            response = client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 250,
                    "unit": "g",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["dish_id"], 1)
        self.assertEqual(response.json()["inventory_item_id"], item["id"])

    def test_technical_recipe_can_be_read_as_domain_aggregate(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Recipe aggregate item",
                    "unit": "kg",
                    "current_stock": 3,
                    "minimum_stock": 1,
                    "ideal_stock": 5,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 0.5,
                    "unit": "kg",
                },
            )

        with self.SessionTesting() as db:
            recipe = get_recipe(db, restaurant_id=1, dish_id=1)

        self.assertTrue(recipe.is_complete)
        self.assertEqual(recipe.dish_id, 1)
        self.assertEqual(recipe.items[0].ingredient.name, "Recipe aggregate item")
        self.assertEqual(recipe.items[0].quantity, 0.5)

    def test_technical_recipe_rejects_duplicate_ingredient(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Duplicado receta",
                    "unit": "kg",
                    "current_stock": 4,
                    "minimum_stock": 1,
                    "ideal_stock": 6,
                },
            ).json()
            payload = {
                "restaurant_id": 1,
                "dish_id": 1,
                "inventory_item_id": item["id"],
                "quantity": 1,
                "unit": "kg",
            }
            first = client.post("/api/inventory/dish-ingredients", json=payload)
            second = client.post("/api/inventory/dish-ingredients", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["error"]["code"], "duplicate_recipe_ingredient")

    def test_technical_recipe_rejects_invalid_unit(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Unidad invalida receta",
                    "unit": "kg",
                    "current_stock": 4,
                    "minimum_stock": 1,
                    "ideal_stock": 6,
                },
            ).json()
            response = client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "oz",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_recipe_unit")

    def test_technical_recipe_rejects_negative_quantity(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Cantidad negativa receta",
                    "unit": "kg",
                    "current_stock": 4,
                    "minimum_stock": 1,
                    "ideal_stock": 6,
                },
            ).json()
            response = client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": -1,
                    "unit": "kg",
                },
            )

        self.assertEqual(response.status_code, 422)

    def test_technical_recipe_rejects_missing_references(self):
        with TestClient(app) as client:
            missing_dish = client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 9999,
                    "inventory_item_id": 9999,
                    "quantity": 1,
                    "unit": "kg",
                },
            )
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Referencia receta",
                    "unit": "kg",
                    "current_stock": 4,
                    "minimum_stock": 1,
                    "ideal_stock": 6,
                },
            ).json()
            missing_item = client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"] + 9999,
                    "quantity": 1,
                    "unit": "kg",
                },
            )

        self.assertEqual(missing_dish.status_code, 404)
        self.assertEqual(missing_dish.json()["error"]["code"], "dish_not_found")
        self.assertEqual(missing_item.status_code, 404)
        self.assertEqual(missing_item.json()["error"]["code"], "inventory_item_not_found")

    def test_technical_recipe_empty_recipe_is_controlled_error(self):
        with self.SessionTesting() as db:
            with self.assertRaises(AppError) as raised:
                require_recipe_items(db, restaurant_id=1, dish_id=1)

        self.assertEqual(raised.exception.code, "recipe_empty")

    def test_inventory_alerts_include_critical_items(self):
        with TestClient(app) as client:
            client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Albahaca alerta",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 3,
                },
            )
            response = client.get("/api/inventory/alerts?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(alert["severity"] == "critical" for alert in response.json()))

    def test_inventory_movement_rejects_negative_stock(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Salmon",
                    "unit": "kg",
                    "current_stock": 1,
                    "minimum_stock": 1,
                    "ideal_stock": 3,
                },
            ).json()
            response = client.post(
                "/api/inventory/movements",
                json={
                    "restaurant_id": 1,
                    "inventory_item_id": item["id"],
                    "movement_type": "OUT",
                    "quantity": 5,
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "inventory_stock_negative")

    def test_inventory_insights_use_analytics_interest(self):
        with self.SessionTesting() as db:
            item = InventoryItem(
                restaurant_id=1,
                name="Mozzarella insight",
                unit="g",
                current_stock=100,
                minimum_stock=150,
                ideal_stock=500,
            )
            db.add(item)
            db.flush()
            db.add(
                DishIngredient(
                    restaurant_id=1,
                    dish_id=1,
                    inventory_item_id=item.id,
                    quantity=150,
                    unit="g",
                )
            )
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/inventory/insights?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        insight_types = [insight["insight_type"] for insight in response.json()]
        self.assertIn("critical_stock_interest", insight_types)

    def test_inventory_insights_explain_missing_inventory(self):
        with TestClient(app) as client:
            response = client.get("/api/inventory/insights?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload[0]["insight_type"], "inventory_setup")
        self.assertEqual(payload[0]["priority"], "opportunity")

    def test_inventory_insights_explain_missing_recipe_links(self):
        with TestClient(app) as client:
            client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Harina sin receta",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 2,
                    "ideal_stock": 8,
                },
            )
            response = client.get("/api/inventory/insights?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload[0]["insight_type"], "dish_ingredient_setup")
        self.assertEqual(payload[0]["priority"], "opportunity")

    def test_inventory_overview_returns_commercial_summary(self):
        with self.SessionTesting() as db:
            result = seed_demo_database(db)

        with TestClient(app) as client:
            response = client.get(f"/api/inventory/overview?restaurant_id={result['restaurant_id']}&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_items"], 10)
        self.assertIn("inventory_health_percentage", payload)
        self.assertGreaterEqual(payload["critical_items"], 1)
        self.assertGreaterEqual(len(payload["top_critical_items"]), 1)
        self.assertGreaterEqual(len(payload["recommended_actions"]), 1)
        self.assertGreaterEqual(len(payload["dishes_at_risk"]), 1)

    def test_prediction_demand_forecast_uses_real_analytics(self):
        with self.SessionTesting() as db:
            result = seed_demo_database(db)

        with TestClient(app) as client:
            response = client.get(f"/api/predictions/demand?restaurant_id={result['restaurant_id']}&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload), 1)
        self.assertGreater(payload[0]["recent_views"], 0)
        self.assertIn(payload[0]["demand_level"], {"high", "medium", "low"})

    def test_prediction_inventory_forecast_detects_stock_pressure(self):
        with self.SessionTesting() as db:
            result = seed_demo_database(db)

        with TestClient(app) as client:
            response = client.get(f"/api/predictions/inventory?restaurant_id={result['restaurant_id']}&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        risk_levels = {item["risk_level"] for item in payload}
        self.assertTrue(risk_levels & {"critical", "warning"})

    def test_prediction_overview_returns_operational_recommendations(self):
        with self.SessionTesting() as db:
            result = seed_demo_database(db)

        with TestClient(app) as client:
            response = client.get(f"/api/predictions/overview?restaurant_id={result['restaurant_id']}&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload["confidence_level"], {"high", "medium", "low"})
        self.assertGreaterEqual(len(payload["dishes_likely_to_sell"]), 1)
        self.assertGreaterEqual(len(payload["ingredients_likely_to_run_low"]), 1)
        self.assertGreaterEqual(len(payload["preparation_recommendations"]), 1)
        self.assertGreaterEqual(len(payload["purchase_recommendations"]), 1)
        self.assertIn("explanation", payload)

    def test_prediction_overview_is_honest_without_analytics(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Queso prediccion",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 2,
                    "ideal_stock": 8,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 0.2,
                    "unit": "kg",
                },
            )
            response = client.get("/api/predictions/overview?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["confidence_level"], "low")
        self.assertEqual(payload["dishes_likely_to_sell"], [])
        self.assertIn("vistas de platos", payload["explanation"])

    def test_prediction_overview_is_honest_without_dish_ingredient_links(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Harina prediction",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 2,
                    "ideal_stock": 8,
                },
            )
            response = client.get("/api/predictions/overview?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["confidence_level"], "low")
        self.assertIn("relaciones plato-ingrediente", payload["explanation"])

    def test_prediction_purchase_recommendation_is_deterministic_for_critical_ingredients(self):
        with self.SessionTesting() as db:
            item = InventoryItem(
                restaurant_id=1,
                name="Mozzarella prediction",
                unit="kg",
                current_stock=1,
                minimum_stock=2,
                ideal_stock=5,
            )
            db.add(item)
            db.flush()
            db.add(DishIngredient(restaurant_id=1, dish_id=1, inventory_item_id=item.id, quantity=0.2, unit="kg"))
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            first = client.get("/api/predictions/overview?restaurant_id=1&range=all").json()
            second = client.get("/api/predictions/overview?restaurant_id=1&range=all").json()

        self.assertEqual(first, second)
        self.assertTrue(any(item["name"] == "Mozzarella prediction" for item in first["purchase_recommendations"]))

    def test_dashboard_page_includes_operations_section(self):
        with TestClient(app) as client:
            response = client.get("/admin/dashboard?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Salud operativa", response.text)
        self.assertIn("Inventario + demanda", response.text)
        self.assertIn("Prediccion operativa", response.text)

    def test_operational_sale_consumes_inventory_and_records_movements(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Harina venta",
                    "unit": "g",
                    "current_stock": 1000,
                    "minimum_stock": 200,
                    "ideal_stock": 1500,
                    "cost": 0.01,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 250,
                    "unit": "g",
                },
            )
            response = client.post(
                "/api/operations/sales",
                json={"restaurant_id": 1, "dish_id": 1, "quantity": 2, "source": "manual"},
            )
            refreshed = client.get("/api/inventory/items?restaurant_id=1").json()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dish_id"], 1)
        self.assertEqual(payload["quantity"], 2)
        self.assertEqual(payload["consumed_ingredients"][0]["quantity"], 500)
        self.assertEqual(payload["consumed_ingredients"][0]["historical_unit_cost"], 0.01)
        self.assertEqual(payload["consumed_ingredients"][0]["historical_total_cost"], 5)
        self.assertEqual(len(payload["movement_ids"]), 1)
        harina = next(item for item in refreshed if item["name"] == "Harina venta")
        self.assertEqual(harina["current_stock"], 500)

        with self.SessionTesting() as db:
            movements = list(
                db.scalars(
                    select(InventoryMovement)
                    .where(InventoryMovement.inventory_item_id == item["id"])
                    .order_by(InventoryMovement.id)
                ).all()
            )

        self.assertEqual(len(movements), 2)
        self.assertEqual(movements[0].movement_type, "IN")
        self.assertEqual(movements[1].movement_type, "OUT")
        self.assertEqual(movements[1].quantity, 500)
        self.assertEqual(movements[1].unit, "g")
        self.assertEqual(movements[1].reason, "sale")
        self.assertEqual(movements[1].origin_type, "sale")
        self.assertEqual(movements[1].origin_id, "manual:dish:1")
        self.assertEqual(movements[1].historical_unit_cost, 0.01)
        self.assertEqual(movements[1].historical_total_cost, 5)

    def test_operational_sale_generates_analytics_only_after_success(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Queso venta",
                    "unit": "g",
                    "current_stock": 800,
                    "minimum_stock": 200,
                    "ideal_stock": 1200,
                    "cost": 0.02,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 100,
                    "unit": "g",
                },
            )
            response = client.post(
                "/api/operations/sales",
                json={"restaurant_id": 1, "dish_id": 1, "quantity": 1, "source": "qr"},
            )

        self.assertEqual(response.status_code, 200)
        with self.SessionTesting() as db:
            event = db.scalar(select(AnalyticsEvent).where(AnalyticsEvent.event_type == "sale_processed"))

        self.assertIsNotNone(event)
        self.assertEqual(event.restaurant_id, 1)
        self.assertEqual(event.dish_id, 1)
        self.assertIn('"source":"qr"', event.metadata_json)

    def test_operational_sale_preserves_historical_cost_after_cost_changes(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Venta historico coste",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                    "cost": 7,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 0.5,
                    "unit": "kg",
                },
            )
            sale = client.post(
                "/api/operations/sales",
                json={"restaurant_id": 1, "dish_id": 1, "quantity": 2, "source": "manual"},
            ).json()
            client.patch(f"/api/inventory/items/{item['id']}", json={"cost": 20})

        self.assertEqual(sale["consumed_ingredients"][0]["historical_unit_cost"], 7)
        self.assertEqual(sale["consumed_ingredients"][0]["historical_total_cost"], 7)
        with self.SessionTesting() as db:
            movement = db.get(InventoryMovement, sale["movement_ids"][0])

        self.assertEqual(movement.historical_unit_cost, 7)
        self.assertEqual(movement.historical_total_cost, 7)

    def test_operational_sale_rolls_back_when_cost_is_missing(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Venta sin coste",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                },
            )
            response = client.post(
                "/api/operations/sales",
                json={"restaurant_id": 1, "dish_id": 1, "quantity": 1, "source": "manual"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "sale_cost_missing")
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            sale_movements = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.inventory_item_id == item["id"],
                    InventoryMovement.movement_type == "OUT",
                )
            )

        self.assertEqual(refreshed_item.current_stock, 5)
        self.assertEqual(sale_movements, 0)

    def test_operational_sale_updates_prediction_with_real_sales(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Tomate venta prediction",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                    "cost": 2,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 0.2,
                    "unit": "kg",
                },
            )
            sale = client.post(
                "/api/operations/sales",
                json={"restaurant_id": 1, "dish_id": 1, "quantity": 3, "source": "pos"},
            ).json()
            prediction = client.get("/api/predictions/overview?restaurant_id=1&range=all").json()

        self.assertTrue(any(item["dish_id"] == 1 for item in sale["prediction"]["demand_forecast"]))
        self.assertTrue(any(item["dish_id"] == 1 for item in prediction["dishes_likely_to_sell"]))
        self.assertIn("ventas reales", prediction["demand_forecast"][0]["explanation"])

    def test_operational_sale_rolls_back_when_prediction_fails(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Rollback venta",
                    "unit": "kg",
                    "current_stock": 3,
                    "minimum_stock": 1,
                    "ideal_stock": 6,
                    "cost": 2,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                },
            )
            with patch(
                "app.services.operational_transaction_service.get_prediction_overview",
                side_effect=RuntimeError("prediction failed"),
            ):
                response = client.post(
                    "/api/operations/sales",
                    json={"restaurant_id": 1, "dish_id": 1, "quantity": 2, "source": "manual"},
                )

        self.assertEqual(response.status_code, 500)
        with self.SessionTesting() as db:
            refreshed_item = db.get(InventoryItem, item["id"])
            movement_count = db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.inventory_item_id == item["id"],
                    InventoryMovement.movement_type == "OUT",
                )
            )
            sale_event_count = db.scalar(
                select(func.count()).select_from(AnalyticsEvent).where(AnalyticsEvent.event_type == "sale_processed")
            )

        self.assertEqual(refreshed_item.current_stock, 3)
        self.assertEqual(movement_count, 0)
        self.assertEqual(sale_event_count, 0)

    def test_dish_costing_calculates_cost_margin_and_breakdown(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Mozzarella costing",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 1,
                    "ideal_stock": 8,
                    "cost": 10,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 0.2,
                    "unit": "kg",
                },
            )
            response = client.get("/api/restaurants/1/dishes/1/costing")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        sale_price = payload["sale_price"]
        self.assertEqual(payload["dish_id"], 1)
        self.assertEqual(payload["total_cost"], 2)
        self.assertEqual(payload["gross_margin"], round(sale_price - 2, 2))
        self.assertEqual(payload["margin_percentage"], round(((sale_price - 2) / sale_price) * 100, 2))
        self.assertTrue(payload["has_recipe"])
        self.assertFalse(payload["missing_costs"])
        self.assertEqual(payload["ingredients_breakdown"][0]["ingredient_name"], "Mozzarella costing")
        self.assertEqual(payload["ingredients_breakdown"][0]["line_cost"], 2)

    def test_dish_costing_returns_empty_costing_without_recipe(self):
        with TestClient(app) as client:
            response = client.get("/api/restaurants/1/dishes/1/costing")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_cost"], 0)
        self.assertEqual(payload["gross_margin"], payload["sale_price"])
        self.assertFalse(payload["has_recipe"])
        self.assertFalse(payload["missing_costs"])
        self.assertEqual(payload["ingredients_breakdown"], [])

    def test_dish_costing_marks_missing_ingredient_cost_as_zero(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Albahaca sin coste",
                    "unit": "g",
                    "current_stock": 100,
                    "minimum_stock": 10,
                    "ideal_stock": 200,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 20,
                    "unit": "g",
                },
            )
            response = client.get("/api/restaurants/1/dishes/1/costing")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_cost"], 0)
        self.assertTrue(payload["missing_costs"])
        self.assertTrue(payload["ingredients_breakdown"][0]["missing_cost"])
        self.assertEqual(payload["ingredients_breakdown"][0]["unit_cost"], 0)

    def test_dish_costing_handles_zero_sale_price_without_division_by_zero(self):
        with self.SessionTesting() as db:
            category = Category(name="Costing Zero", restaurant_id=1)
            db.add(category)
            db.flush()
            dish = Dish(
                name="Agua cortesia",
                description="",
                price=0,
                ingredients="",
                allergens="",
                image="",
                category_id=category.id,
                restaurant_id=1,
            )
            db.add(dish)
            db.flush()
            item = InventoryItem(
                restaurant_id=1,
                name="Vaso costing",
                unit="unit",
                current_stock=100,
                minimum_stock=10,
                ideal_stock=200,
                cost=0.25,
            )
            db.add(item)
            db.flush()
            db.add(
                DishIngredient(
                    restaurant_id=1,
                    dish_id=dish.id,
                    inventory_item_id=item.id,
                    quantity=1,
                    unit="unit",
                )
            )
            db.commit()
            dish_id = dish.id

        with TestClient(app) as client:
            response = client.get(f"/api/restaurants/1/dishes/{dish_id}/costing")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["sale_price"], 0)
        self.assertEqual(payload["total_cost"], 0.25)
        self.assertEqual(payload["gross_margin"], -0.25)
        self.assertIsNone(payload["margin_percentage"])

    def test_dish_costing_is_isolated_by_restaurant(self):
        with self.SessionTesting() as db:
            restaurant = Restaurant(name="Costing Tenant", slug="costing-tenant")
            db.add(restaurant)
            db.flush()
            db.add(
                RestaurantMembership(
                    user_id=1,
                    restaurant_id=restaurant.id,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                )
            )
            category = Category(name="Costing", restaurant_id=restaurant.id)
            db.add(category)
            db.flush()
            dish = Dish(
                name="Tenant Dish",
                description="",
                price=12,
                ingredients="",
                allergens="",
                image="",
                category_id=category.id,
                restaurant_id=restaurant.id,
            )
            db.add(dish)
            db.flush()
            item = InventoryItem(
                restaurant_id=restaurant.id,
                name="Tenant Ingredient",
                unit="kg",
                current_stock=3,
                minimum_stock=1,
                ideal_stock=5,
                cost=4,
            )
            db.add(item)
            db.flush()
            db.add(
                DishIngredient(
                    restaurant_id=restaurant.id,
                    dish_id=dish.id,
                    inventory_item_id=item.id,
                    quantity=2,
                    unit="kg",
                )
            )
            db.commit()
            restaurant_id = restaurant.id
            dish_id = dish.id

        with TestClient(app) as client:
            wrong_tenant = client.get(f"/api/restaurants/1/dishes/{dish_id}/costing")
            response = client.get(f"/api/restaurants/{restaurant_id}/costing/dishes")

        self.assertEqual(wrong_tenant.status_code, 404)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["restaurant_id"], restaurant_id)
        self.assertEqual(len(payload["dishes"]), 1)
        self.assertEqual(payload["dishes"][0]["total_cost"], 8)

    def test_inventory_planning_handles_item_without_movements(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Sin historico planning",
                    "unit": "kg",
                    "current_stock": 10,
                    "minimum_stock": 2,
                    "ideal_stock": 12,
                },
            ).json()
            response = client.get(f"/api/inventory/planning/items/{item['id']}?restaurant_id=1&range=30d")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["has_consumption_data"])
        self.assertIsNone(payload["average_daily_consumption"])
        self.assertIsNone(payload["estimated_days_remaining"])
        self.assertEqual(payload["historical_consumption"], 0)

    def test_inventory_planning_marks_out_of_stock_item(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Sin stock planning",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 2,
                    "ideal_stock": 5,
                },
            ).json()
            response = client.get(f"/api/inventory/planning/items/{item['id']}?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "out_of_stock")
        self.assertEqual(payload["replenishment_priority"], "urgent")

    def test_inventory_planning_marks_critical_item(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Critico planning",
                    "unit": "kg",
                    "current_stock": 1,
                    "minimum_stock": 2,
                    "ideal_stock": 5,
                },
            ).json()
            response = client.get("/api/inventory/planning/critical?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(any(entry["inventory_item_id"] == item["id"] for entry in payload))
        critical = next(entry for entry in payload if entry["inventory_item_id"] == item["id"])
        self.assertEqual(critical["status"], "critical")

    def test_inventory_planning_estimates_days_remaining_from_history(self):
        with self.SessionTesting() as db:
            item = InventoryItem(
                restaurant_id=1,
                name="Historico planning",
                unit="kg",
                current_stock=6,
                minimum_stock=1,
                ideal_stock=10,
            )
            db.add(item)
            db.flush()
            db.add(
                InventoryMovement(
                    restaurant_id=1,
                    inventory_item_id=item.id,
                    movement_type="OUT",
                    quantity=6,
                    created_at=datetime.utcnow() - timedelta(days=2),
                )
            )
            db.commit()
            item_id = item.id

        with TestClient(app) as client:
            response = client.get(f"/api/inventory/planning/items/{item_id}?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["has_consumption_data"])
        self.assertEqual(payload["historical_consumption"], 6)
        self.assertEqual(payload["average_daily_consumption"], 2)
        self.assertEqual(payload["estimated_days_remaining"], 3)

    def test_inventory_planning_reports_dish_impact(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Impacto planning",
                    "unit": "kg",
                    "current_stock": 0.5,
                    "minimum_stock": 0.2,
                    "ideal_stock": 2,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 1,
                    "unit": "kg",
                },
            )
            response = client.get(f"/api/inventory/planning/items/{item['id']}?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["affected_dishes_count"], 1)
        self.assertEqual(payload["blocked_dishes_count"], 1)
        self.assertEqual(payload["impacted_dishes"][0]["dish_id"], 1)
        self.assertTrue(payload["impacted_dishes"][0]["is_blocked"])

    def test_inventory_planning_is_isolated_by_restaurant(self):
        with self.SessionTesting() as db:
            restaurant = Restaurant(name="Planning Tenant", slug="planning-tenant")
            db.add(restaurant)
            db.flush()
            db.add(
                RestaurantMembership(
                    user_id=1,
                    restaurant_id=restaurant.id,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                )
            )
            item = InventoryItem(
                restaurant_id=restaurant.id,
                name="Tenant Planning Ingredient",
                unit="kg",
                current_stock=1,
                minimum_stock=2,
                ideal_stock=5,
            )
            db.add(item)
            db.commit()
            restaurant_id = restaurant.id
            item_id = item.id

        with TestClient(app) as client:
            wrong_tenant = client.get(f"/api/inventory/planning/items/{item_id}?restaurant_id=1")
            right_tenant = client.get(f"/api/inventory/planning?restaurant_id={restaurant_id}")

        self.assertEqual(wrong_tenant.status_code, 404)
        self.assertEqual(right_tenant.status_code, 200)
        payload = right_tenant.json()
        self.assertEqual(payload["restaurant_id"], restaurant_id)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["inventory_item_id"], item_id)

    def test_business_insights_handles_restaurant_without_data(self):
        with TestClient(app) as client:
            created = client.post("/api/restaurants", json={"name": "Business Empty"}).json()
            response = client.get(f"/api/business/insights?restaurant_id={created['id']}&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["executive_summary"]["processed_sales"], 0)
        self.assertEqual(payload["executive_summary"]["dishes_sold"], 0)
        self.assertEqual(payload["health_score"]["score"], 100)
        self.assertEqual(payload["health_score"]["classification"], "Excelente")
        self.assertEqual(payload["risks"], [])

    def test_business_insights_returns_executive_summary_for_complete_data(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Business tomate",
                    "unit": "kg",
                    "current_stock": 5,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                    "cost": 2,
                },
            ).json()
            client.post(
                "/api/inventory/dish-ingredients",
                json={
                    "restaurant_id": 1,
                    "dish_id": 1,
                    "inventory_item_id": item["id"],
                    "quantity": 0.5,
                    "unit": "kg",
                },
            )
            sale = client.post(
                "/api/operations/sales",
                json={"restaurant_id": 1, "dish_id": 1, "quantity": 2, "source": "manual"},
            )
            response = client.get("/api/business/insights?restaurant_id=1&range=all")

        self.assertEqual(sale.status_code, 200)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        summary = payload["executive_summary"]
        self.assertEqual(summary["processed_sales"], 1)
        self.assertEqual(summary["dishes_sold"], 2)
        self.assertGreater(summary["estimated_total_cost"], 0)
        self.assertIsNotNone(summary["average_margin_percentage"])
        self.assertGreaterEqual(len(payload["opportunities"]), 1)

    def test_business_insights_detects_critical_ingredients(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Business critico",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 3,
                },
            ).json()
            response = client.get("/api/business/insights?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["executive_summary"]["critical_ingredients"], 1)
        self.assertTrue(any(risk["inventory_item_id"] == item["id"] for risk in payload["risks"]))

    def test_business_insights_detects_low_margin(self):
        with self.SessionTesting() as db:
            category = Category(name="Business Margin", restaurant_id=1)
            db.add(category)
            db.flush()
            dish = Dish(
                name="Low Margin Dish",
                description="",
                price=10,
                ingredients="",
                allergens="",
                image="",
                category_id=category.id,
                restaurant_id=1,
            )
            db.add(dish)
            db.flush()
            item = InventoryItem(
                restaurant_id=1,
                name="Expensive Ingredient",
                unit="kg",
                current_stock=5,
                minimum_stock=1,
                ideal_stock=4,
                cost=8,
            )
            db.add(item)
            db.flush()
            db.add(
                DishIngredient(
                    restaurant_id=1,
                    dish_id=dish.id,
                    inventory_item_id=item.id,
                    quantity=1,
                    unit="kg",
                )
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/business/insights?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        risk_types = [risk["type"] for risk in response.json()["risks"]]
        self.assertIn("margin", risk_types)

    def test_business_insights_detects_incomplete_recipes(self):
        with self.SessionTesting() as db:
            category = Category(name="Business Recipe", restaurant_id=1)
            db.add(category)
            db.flush()
            dish = Dish(
                name="Recipe Missing Dish",
                description="",
                price=11,
                ingredients="",
                allergens="",
                image="",
                category_id=category.id,
                restaurant_id=1,
            )
            db.add(dish)
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/business/insights?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        risk_titles = [risk["title"] for risk in response.json()["risks"]]
        self.assertTrue(any("Recipe Missing Dish" in title for title in risk_titles))

    def test_business_priorities_are_generated_from_risks(self):
        with TestClient(app) as client:
            item = client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Priority stock",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                },
            ).json()
            response = client.get("/api/business/priorities?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(any(priority["inventory_item_id"] == item["id"] for priority in payload))
        self.assertIn(payload[0]["severity"], {"critical", "warning"})

    def test_business_health_score_reflects_operational_risk(self):
        with TestClient(app) as client:
            client.post(
                "/api/inventory/items",
                json={
                    "restaurant_id": 1,
                    "name": "Health stock",
                    "unit": "kg",
                    "current_stock": 0,
                    "minimum_stock": 1,
                    "ideal_stock": 4,
                },
            )
            response = client.get("/api/business/health?restaurant_id=1&range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertLess(payload["score"], 100)
        self.assertIn(payload["classification"], {"Buena", "Mejorable", "Critica"})


if __name__ == "__main__":
    unittest.main()
