import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import httpx2
from fastapi.testclient import TestClient
from openai import APITimeoutError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.rate_limit import SlidingWindowRateLimiter
from app.database import Base, get_db
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import AnalyticsEvent, Restaurant, RestaurantMembership, User
from app.routers import analytics as analytics_router
from app.services.openai_service import OpenAIService


class PublicSurfaceHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/hardening.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        with cls.SessionTesting() as db:
            db.add(Restaurant(id=301, name="Hardening Restaurant", slug="hardening-restaurant"))
            db.add_all(
                [
                    User(id=301, email="owner@hardening.local", hashed_password="x", role="owner", is_active=True),
                    User(id=302, email="cook@hardening.local", hashed_password="x", role="cook", is_active=True),
                ]
            )
            db.flush()
            db.add_all(
                [
                    RestaurantMembership(user_id=301, restaurant_id=301, role="owner", is_active=True),
                    RestaurantMembership(user_id=302, restaurant_id=301, role="cook", is_active=True),
                ]
            )
            db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.temp_dir.cleanup()

    def setUp(self):
        def override_get_db():
            db = self.SessionTesting()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        analytics_router.analytics_rate_limiter.reset()

    def tearDown(self):
        app.dependency_overrides.clear()
        analytics_router.analytics_rate_limiter.reset()

    def _authenticate_as(self, user_id: int) -> None:
        user = User(
            id=user_id,
            email=f"user-{user_id}@hardening.local",
            hashed_password="not-used",
            is_active=True,
            created_at=datetime.utcnow(),
        )
        app.dependency_overrides[get_current_user] = lambda: user

    def _count_events(self, event_type: str) -> int:
        with self.SessionTesting() as db:
            return db.scalar(
                select(func.count()).select_from(AnalyticsEvent).where(AnalyticsEvent.event_type == event_type)
            )

    # --- AI image prompt -------------------------------------------------

    def test_image_prompt_requires_authentication(self):
        with patch("app.routers.ai.suggest_image_prompt") as suggest:
            with TestClient(app) as client:
                response = client.get("/ai/image-prompt?dish_name=pizza")

        self.assertEqual(response.status_code, 401)
        suggest.assert_not_called()

    def test_image_prompt_requires_menu_management_permission(self):
        self._authenticate_as(302)
        with patch("app.routers.ai.suggest_image_prompt") as suggest:
            with TestClient(app) as client:
                response = client.get("/ai/image-prompt?dish_name=pizza&restaurant_id=301")

        self.assertEqual(response.status_code, 403)
        suggest.assert_not_called()

    def test_image_prompt_allows_owner_and_bounds_input(self):
        self._authenticate_as(301)
        with patch("app.routers.ai.suggest_image_prompt", return_value={"prompt": "ok"}) as suggest:
            with TestClient(app) as client:
                allowed = client.get("/ai/image-prompt?dish_name=pizza&restaurant_id=301")
                too_long = client.get(f"/ai/image-prompt?dish_name={'x' * 121}&restaurant_id=301")

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json(), {"prompt": "ok"})
        self.assertEqual(too_long.status_code, 422)
        suggest.assert_called_once_with(dish_name="pizza", style="modern restaurant")

    # --- Public analytics ------------------------------------------------

    def test_public_analytics_rejects_business_events(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/analytics/events",
                json={"restaurant_id": 301, "event_type": "sale_processed", "metadata": {"total": "999.00"}},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_analytics_event_type")
        self.assertEqual(self._count_events("sale_processed"), 0)

    def test_public_analytics_rejects_oversized_metadata(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/analytics/events",
                json={"restaurant_id": 301, "event_type": "search", "metadata": {"search_query": "x" * 3000}},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "analytics_metadata_too_large")

    def test_public_analytics_is_rate_limited_per_client(self):
        limiter = SlidingWindowRateLimiter(limit=3, window_seconds=60)
        with patch.object(analytics_router, "analytics_rate_limiter", limiter):
            with TestClient(app) as client:
                statuses = [
                    client.post(
                        "/api/analytics/events",
                        json={"restaurant_id": 301, "event_type": "menu_view"},
                    )
                    for _ in range(4)
                ]

        self.assertEqual([r.status_code for r in statuses], [200, 200, 200, 429])
        self.assertEqual(statuses[-1].json()["error"]["code"], "analytics_rate_limited")
        self.assertIn("Retry-After", statuses[-1].headers)

    def test_sliding_window_limiter_releases_after_window(self):
        now = [1000.0]
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10, clock=lambda: now[0])

        self.assertEqual(limiter.hit("ip"), 0)
        self.assertEqual(limiter.hit("ip"), 0)
        self.assertEqual(limiter.hit("ip"), 10)
        self.assertEqual(limiter.hit("other-ip"), 0)
        now[0] += 10
        self.assertEqual(limiter.hit("ip"), 0)


class OpenAIServiceResilienceTests(unittest.TestCase):
    def _service_with_client(self, client) -> OpenAIService:
        service = OpenAIService()
        service.client = client
        return service

    def test_provider_errors_return_controlled_payload(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = APITimeoutError(
            request=httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
        )

        result = self._service_with_client(client).json_completion(system="s", prompt="p")

        self.assertEqual(result, {"error": "AI service unavailable"})

    def test_non_object_json_is_rejected(self):
        client = MagicMock()
        client.chat.completions.create.return_value.choices = [MagicMock(message=MagicMock(content="[1, 2]"))]

        result = self._service_with_client(client).json_completion(system="s", prompt="p")

        self.assertEqual(result, {"error": "Invalid AI response"})

    def test_client_is_built_with_timeout_and_bounded_retries(self):
        with (
            patch("app.services.openai_service.settings") as fake_settings,
            patch("app.services.openai_service.OpenAI") as openai_cls,
        ):
            fake_settings.openai_api_key = "test-key"
            fake_settings.openai_timeout_seconds = 7.5
            fake_settings.openai_max_retries = 1
            OpenAIService()

        openai_cls.assert_called_once_with(api_key="test-key", timeout=7.5, max_retries=1)


if __name__ == "__main__":
    unittest.main()
