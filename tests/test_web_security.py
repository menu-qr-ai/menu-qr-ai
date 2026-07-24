import hmac
import re
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, settings
from app.core.rate_limit import LoginRateLimiter
from app.core.security import hash_password
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.session import (
    CSRF_TOKEN_KEY,
    SESSION_COOKIE_NAME,
    SESSION_ID_KEY,
    SignedSessionMiddleware,
    rotate_authenticated_session,
)
from app.database import Base, get_db
from app.main import app
from app.models import (
    AnalyticsEvent,
    Restaurant,
    RestaurantMembership,
    User,
)
from app.services.login_security_service import login_rate_limiter


TEST_PASSWORD = "Web-security-password-2026"


class WebSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/security.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=cls.engine,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls._seed_database()

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
    def _seed_database(cls):
        with cls.SessionTesting() as db:
            db.add(
                Restaurant(
                    id=201,
                    name="Security Restaurant",
                    slug="security-restaurant",
                    currency="EUR",
                )
            )
            roles = ("owner", "manager", "waiter", "cook", "viewer")
            for offset, role in enumerate(roles, start=1):
                user_id = 200 + offset
                db.add(
                    User(
                        id=user_id,
                        email=f"security-{role}@hostai.test",
                        hashed_password=hash_password(TEST_PASSWORD),
                        full_name=f"Security {role.title()}",
                        role=role,
                        restaurant_id=201,
                        is_active=True,
                    )
                )
                db.add(
                    RestaurantMembership(
                        user_id=user_id,
                        restaurant_id=201,
                        role=role,
                        is_active=True,
                        created_by_user_id=201,
                    )
                )
            db.commit()

    def setUp(self):
        login_rate_limiter.reset()
        with self.SessionTesting() as db:
            db.execute(delete(AnalyticsEvent))
            db.execute(
                RestaurantMembership.__table__.update().values(
                    is_active=True
                )
            )
            db.execute(User.__table__.update().values(is_active=True))
            db.commit()

    def _login(
        self,
        client: TestClient,
        role: str = "owner",
        *,
        password: str = TEST_PASSWORD,
    ):
        return client.post(
            "/api/auth/login",
            json={
                "email": f"security-{role}@hostai.test",
                "password": password,
            },
        )

    @staticmethod
    def _csrf_from_html(html: str) -> str:
        match = re.search(
            r'name="csrf_token" value="([^"]+)"',
            html,
        )
        if match is None:
            raise AssertionError("CSRF field not found")
        return match.group(1)

    @staticmethod
    def _middleware(
        *,
        max_age: int | None = None,
        https_only: bool = False,
    ) -> SignedSessionMiddleware:
        return SignedSessionMiddleware(
            app=lambda scope, receive, send: None,
            secret_key=settings.secret_key,
            https_only=https_only,
            max_age=max_age or settings.session_max_age_seconds,
            trusted_origins=("http://testserver",),
        )

    def test_csrf_header_missing_invalid_other_session_and_valid(self):
        with TestClient(app) as first, TestClient(app) as second:
            first_login = self._login(first)
            second_login = self._login(second)
            first_token = first_login.json()["csrf_token"]
            second_token = second_login.json()["csrf_token"]

            missing = first.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 201},
            )
            invalid = first.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 201},
                headers={"X-CSRF-Token": "invalid-token"},
            )
            other_session = first.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 201},
                headers={"X-CSRF-Token": second_token},
            )
            valid = first.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 201},
                headers={"X-CSRF-Token": first_token},
            )

        self.assertEqual(missing.status_code, 403)
        self.assertEqual(
            missing.json()["error"]["code"],
            "csrf_token_missing",
        )
        self.assertEqual(invalid.status_code, 403)
        self.assertEqual(
            invalid.json()["error"]["code"],
            "csrf_token_invalid",
        )
        self.assertEqual(other_session.status_code, 403)
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertNotIn(first_token, invalid.text)
        self.assertNotIn(first_token, missing.text)

    def test_form_csrf_valid_missing_and_wrong(self):
        with TestClient(app) as client:
            login = self._login(client)
            token = login.json()["csrf_token"]

            missing = client.post(
                "/app/restaurants/select",
                data={"restaurant_id": 201},
                follow_redirects=False,
            )
            wrong = client.post(
                "/app/restaurants/select",
                data={
                    "restaurant_id": 201,
                    "csrf_token": "wrong",
                },
                follow_redirects=False,
            )
            valid = client.post(
                "/app/restaurants/select",
                data={
                    "restaurant_id": 201,
                    "csrf_token": token,
                },
                follow_redirects=False,
            )

        self.assertEqual(missing.status_code, 403)
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(valid.status_code, 303, valid.text)

    def test_safe_get_and_public_post_are_exempt(self):
        with TestClient(app) as client:
            self._login(client)
            get_response = client.get("/api/access/context")
            public_post = client.post(
                "/api/analytics/events",
                json={
                    "restaurant_id": 201,
                    "event_type": "menu_view",
                },
            )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(public_post.status_code, 200, public_post.text)

    def test_all_unsafe_methods_and_critical_domains_are_protected(self):
        requests = (
            ("PUT", "/api/access/active-restaurant", {"restaurant_id": 201}),
            (
                "PATCH",
                "/api/access/restaurants/201/memberships/1",
                {"role": "viewer"},
            ),
            ("DELETE", "/api/orders/201/1/lines/1", None),
            ("POST", "/api/orders/201/1/fulfill", None),
            ("POST", "/api/dining/201/sessions/1/settle", None),
            (
                "POST",
                "/api/dining/201/settlements/1/payments",
                {
                    "amount": "1.00",
                    "method": "cash",
                    "idempotency_key": "csrf",
                },
            ),
            ("POST", "/api/kitchen/201/tickets/1/start", None),
            (
                "POST",
                "/api/orders/201/sessions/1",
                {},
            ),
            (
                "POST",
                "/api/inventory/items",
                {
                    "restaurant_id": 201,
                    "name": "Protected",
                    "unit": "unit",
                },
            ),
        )
        with TestClient(app) as client:
            self._login(client)
            for method, path, payload in requests:
                with self.subTest(method=method, path=path):
                    response = client.request(
                        method,
                        path,
                        json=payload,
                    )
                    self.assertEqual(
                        response.status_code,
                        403,
                        response.text,
                    )
                    self.assertEqual(
                        response.json()["error"]["code"],
                        "csrf_token_missing",
                    )

    def test_origin_is_defense_in_depth(self):
        with TestClient(app) as client:
            token = self._login(client).json()["csrf_token"]
            rejected = client.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 201},
                headers={
                    "X-CSRF-Token": token,
                    "Origin": "https://attacker.invalid",
                },
            )
            accepted = client.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 201},
                headers={
                    "X-CSRF-Token": token,
                    "Origin": "http://testserver",
                },
            )

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(
            rejected.json()["error"]["code"],
            "csrf_token_invalid",
        )
        self.assertEqual(accepted.status_code, 200)

    def test_csrf_uses_constant_time_comparison(self):
        with TestClient(app) as client:
            self._login(client)
            with patch(
                "app.core.session.hmac.compare_digest",
                wraps=hmac.compare_digest,
            ) as compare:
                response = client.put(
                    "/api/access/active-restaurant",
                    json={"restaurant_id": 201},
                    headers={"X-CSRF-Token": "wrong"},
                )
        self.assertEqual(response.status_code, 403)
        self.assertGreaterEqual(compare.call_count, 2)

    def test_login_rotates_session_and_csrf(self):
        middleware = self._middleware()
        with TestClient(app) as client:
            login_page = client.get("/login")
            anonymous_cookie = client.cookies.get(SESSION_COOKIE_NAME)
            anonymous = middleware._decode(anonymous_cookie).data
            anonymous_token = self._csrf_from_html(login_page.text)

            login = self._login(client)
            authenticated_cookie = client.cookies.get(
                SESSION_COOKIE_NAME
            )
            authenticated = middleware._decode(
                authenticated_cookie
            ).data
            old_token_request = client.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 201},
                headers={"X-CSRF-Token": anonymous_token},
            )

        self.assertNotEqual(anonymous_cookie, authenticated_cookie)
        self.assertNotEqual(
            anonymous[SESSION_ID_KEY],
            authenticated[SESSION_ID_KEY],
        )
        self.assertNotEqual(
            anonymous[CSRF_TOKEN_KEY],
            authenticated[CSRF_TOKEN_KEY],
        )
        self.assertEqual(
            login.json()["csrf_token"],
            authenticated[CSRF_TOKEN_KEY],
        )
        self.assertEqual(old_token_request.status_code, 403)

    def test_restaurant_switch_keeps_session_security_identifiers(self):
        middleware = self._middleware()
        with TestClient(app) as client:
            login = self._login(client)
            before = middleware._decode(
                client.cookies.get(SESSION_COOKIE_NAME)
            ).data
            switched = client.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 201},
                headers={
                    "X-CSRF-Token": login.json()["csrf_token"]
                },
            )
            after = middleware._decode(
                client.cookies.get(SESSION_COOKIE_NAME)
            ).data

        self.assertEqual(switched.status_code, 200)
        self.assertEqual(before[SESSION_ID_KEY], after[SESSION_ID_KEY])
        self.assertEqual(
            before[CSRF_TOKEN_KEY],
            after[CSRF_TOKEN_KEY],
        )

    def test_logout_is_protected_clears_cookie_and_is_idempotent(self):
        with TestClient(app) as client:
            token = self._login(client).json()["csrf_token"]
            missing = client.post("/api/auth/logout")
            valid = client.post(
                "/api/auth/logout",
                headers={"X-CSRF-Token": token},
            )
            logged_out = client.get("/api/auth/me")
            repeated = client.post("/api/auth/logout")
            legacy_get = client.get(
                "/logout",
                follow_redirects=False,
            )

        self.assertEqual(missing.status_code, 403)
        self.assertEqual(valid.status_code, 204)
        self.assertEqual(logged_out.status_code, 401)
        self.assertEqual(repeated.status_code, 204)
        self.assertEqual(legacy_get.status_code, 405)
        self.assertIsNone(client.cookies.get(SESSION_COOKIE_NAME))

    def test_absolute_expiration_and_invalid_signatures(self):
        middleware = self._middleware(max_age=300)
        session: dict = {}
        with patch("app.core.session.time.time", return_value=1_000):
            rotate_authenticated_session(session, 201)
            encoded = middleware._encode(session)
        with patch("app.core.session.time.time", return_value=1_299):
            self.assertEqual(
                middleware._decode(encoded).status,
                "valid",
            )
        with patch("app.core.session.time.time", return_value=1_300):
            self.assertEqual(
                middleware._decode(encoded).status,
                "expired",
            )

        payload, signature = encoded.split(".", 1)
        manipulated = f"{payload[:-1]}A.{signature}"
        replacement = "A" if signature[0] != "A" else "B"
        invalid_signature = f"{payload}.{replacement}{signature[1:]}"
        self.assertEqual(
            middleware._decode(manipulated).status,
            "invalid",
        )
        self.assertEqual(
            middleware._decode(invalid_signature).status,
            "invalid",
        )

    def test_expired_and_invalid_sessions_differ_for_api_and_html(self):
        middleware = self._middleware(
            max_age=settings.session_max_age_seconds
        )
        expired_session: dict = {}
        old_time = int(time.time()) - settings.session_max_age_seconds - 1
        with patch(
            "app.core.session.time.time",
            return_value=old_time,
        ):
            rotate_authenticated_session(expired_session, 201)
            expired_cookie = middleware._encode(expired_session)

        with TestClient(app) as client:
            client.cookies.set(SESSION_COOKIE_NAME, expired_cookie)
            api_expired = client.get("/api/auth/me")
            client.cookies.set(SESSION_COOKIE_NAME, expired_cookie)
            html_expired = client.get(
                "/staff/waiter",
                follow_redirects=False,
            )
            client.cookies.set(
                SESSION_COOKIE_NAME,
                f"{expired_cookie}tampered",
            )
            api_invalid = client.get("/api/auth/me")

        self.assertEqual(api_expired.status_code, 401)
        self.assertEqual(
            api_expired.json()["error"]["code"],
            "session_expired",
        )
        self.assertEqual(html_expired.status_code, 303)
        self.assertTrue(
            html_expired.headers["location"].startswith("/login")
        )
        self.assertEqual(api_invalid.status_code, 401)
        self.assertEqual(
            api_invalid.json()["error"]["code"],
            "session_invalid",
        )

    def test_missing_or_inactive_user_invalidates_session(self):
        with TestClient(app) as client:
            login = self._login(client)
            token = login.json()["csrf_token"]
            with self.SessionTesting() as db:
                db.get(User, 201).is_active = False
                db.commit()
            api = client.get("/api/auth/me")
            html = client.get(
                "/admin/dashboard",
                follow_redirects=False,
            )
            mutation = client.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 201},
                headers={"X-CSRF-Token": token},
            )

        self.assertEqual(api.status_code, 401)
        self.assertEqual(
            api.json()["error"]["code"],
            "session_invalid",
        )
        self.assertEqual(html.status_code, 303)
        self.assertEqual(mutation.status_code, 401)

    def test_login_is_non_enumerable_and_rate_limited(self):
        with TestClient(app) as client:
            wrong = client.post(
                "/api/auth/login",
                json={
                    "email": "security-owner@hostai.test",
                    "password": "wrong",
                },
            )
            missing = client.post(
                "/api/auth/login",
                json={
                    "email": "absent@hostai.test",
                    "password": "wrong",
                },
            )
            for _ in range(settings.login_rate_limit_attempts):
                client.post(
                    "/api/auth/login",
                    json={
                        "email": "limited@hostai.test",
                        "password": "wrong",
                    },
                )
            blocked = client.post(
                "/api/auth/login",
                json={
                    "email": "limited@hostai.test",
                    "password": "wrong",
                },
            )

        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.json(), missing.json())
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(
            blocked.json()["error"]["code"],
            "login_rate_limited",
        )
        self.assertIn("Retry-After", blocked.headers)

    def test_rate_limiter_window_dimensions_and_success_cleanup(self):
        clock_value = [100.0]
        limiter = LoginRateLimiter(
            pair_attempts=2,
            window_seconds=60,
            clock=lambda: clock_value[0],
        )
        limiter.record_failure("ip-1", "a@example.test")
        limiter.record_failure("ip-1", "a@example.test")
        self.assertEqual(
            limiter.retry_after("ip-1", "a@example.test"),
            60,
        )
        self.assertEqual(
            limiter.retry_after("ip-2", "a@example.test"),
            0,
        )
        self.assertEqual(
            limiter.retry_after("ip-1", "b@example.test"),
            0,
        )
        limiter.clear_success("ip-1", "a@example.test")
        self.assertEqual(
            limiter.retry_after("ip-1", "a@example.test"),
            0,
        )
        clock_value[0] = 161.0
        self.assertEqual(
            limiter.retry_after("ip-1", "b@example.test"),
            0,
        )

    def test_successful_login_clears_failed_pair_counter(self):
        with TestClient(app) as client:
            for _ in range(
                settings.login_rate_limit_attempts - 1
            ):
                client.post(
                    "/api/auth/login",
                    json={
                        "email": "security-owner@hostai.test",
                        "password": "wrong",
                    },
                )
            success = self._login(client)
            after_success = client.post(
                "/api/auth/login",
                json={
                    "email": "security-owner@hostai.test",
                    "password": "wrong",
                },
            )
        self.assertEqual(success.status_code, 200)
        self.assertEqual(after_success.status_code, 401)

    def test_secret_key_environment_and_cors_validation(self):
        strong_secret = (
            "0123456789abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        )
        production = Settings(
            environment="production",
            secret_key=strong_secret,
            app_url="https://hostai.example",
            cors_origins=("https://hostai.example",),
        )
        development = Settings(
            environment="development",
            secret_key="change-me-in-production",
        )
        test_environment = Settings(
            environment="test",
            secret_key="test-only",
        )

        self.assertTrue(production.is_production)
        self.assertTrue(development.is_development)
        self.assertTrue(test_environment.is_test)
        with self.assertRaises(ValidationError):
            Settings(
                environment="production",
                secret_key="weak",
                app_url="https://hostai.example",
                cors_origins=("https://hostai.example",),
            )
        with self.assertRaises(ValidationError):
            Settings(
                environment="production",
                secret_key=strong_secret,
                app_url="http://hostai.example",
                cors_origins=("https://hostai.example",),
            )
        with self.assertRaises(ValidationError):
            Settings(
                environment="production",
                secret_key=strong_secret,
                app_url="https://hostai.example",
                cors_origins=("*",),
            )

    def test_cookie_attributes_development_and_production(self):
        with TestClient(app) as client:
            response = client.get("/login")
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertIn("path=/", cookie)
        self.assertIn("max-age=", cookie)
        self.assertIn("expires=", cookie)
        self.assertNotIn("secure", cookie)
        self.assertNotIn("domain=", cookie)

        production_app = FastAPI()
        production_app.add_middleware(
            SignedSessionMiddleware,
            secret_key=secrets.token_urlsafe(48),
            https_only=True,
            max_age=300,
            trusted_origins=("https://testserver",),
        )
        production_app.add_middleware(
            SecurityHeadersMiddleware,
            production=True,
        )

        @production_app.get("/session")
        def create_session(request: Request):
            rotate_authenticated_session(request.state.session, 1)
            return {"ok": True}

        with TestClient(
            production_app,
            base_url="https://testserver",
        ) as client:
            production_response = client.get("/session")
        production_cookie = production_response.headers[
            "set-cookie"
        ].lower()
        self.assertIn("secure", production_cookie)
        self.assertIn(
            "strict-transport-security",
            production_response.headers,
        )

    def test_security_headers_cache_and_public_pages(self):
        with TestClient(app) as client:
            login = client.get("/login")
            static_asset = client.get("/static/js/security.js")
            public_menu = client.get("/menu?restaurant_id=201")

        expected_headers = (
            "x-content-type-options",
            "referrer-policy",
            "x-frame-options",
            "content-security-policy",
            "permissions-policy",
        )
        for header in expected_headers:
            self.assertIn(header, login.headers)
        self.assertEqual(
            login.headers["x-content-type-options"],
            "nosniff",
        )
        self.assertEqual(login.headers["x-frame-options"], "DENY")
        self.assertIn("nonce-", login.headers["content-security-policy"])
        self.assertEqual(login.headers["cache-control"], "no-store")
        self.assertNotIn("strict-transport-security", login.headers)
        self.assertEqual(static_asset.status_code, 200)
        self.assertNotIn("cache-control", static_asset.headers)
        self.assertEqual(public_menu.status_code, 200)

    def test_authenticated_pages_are_no_store_and_operational(self):
        destinations = {
            "owner": "/admin/dashboard",
            "manager": "/admin/dashboard",
            "waiter": "/staff/waiter",
            "cook": "/staff/kitchen",
            "viewer": "/admin/dashboard",
        }
        for role, destination in destinations.items():
            with self.subTest(role=role), TestClient(app) as client:
                login = self._login(client, role)
                self.assertEqual(login.status_code, 200, login.text)
                page = client.get(destination)
                self.assertEqual(page.status_code, 200, page.text)
                self.assertEqual(
                    page.headers["cache-control"],
                    "no-store",
                )
                self.assertIn(
                    'meta name="csrf-token"',
                    page.text,
                )

    def test_cors_is_restricted_and_get_dashboard_has_no_session_effect(self):
        with TestClient(app) as client:
            login = self._login(client)
            token = login.json()["csrf_token"]
            selected = client.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 201},
                headers={"X-CSRF-Token": token},
            )
            dashboard = client.get(
                "/admin/dashboard?restaurant_id=201"
            )
            context = client.get("/api/access/context")
            evil_preflight = client.options(
                "/api/access/active-restaurant",
                headers={
                    "Origin": "https://evil.invalid",
                    "Access-Control-Request-Method": "PUT",
                },
            )

        self.assertEqual(selected.status_code, 200)
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(
            context.json()["active_restaurant"]["id"],
            201,
        )
        self.assertNotIn(
            "access-control-allow-origin",
            evil_preflight.headers,
        )

    def test_frontend_uses_shared_csrf_helper_without_local_storage(self):
        project_root = Path(__file__).resolve().parents[1]
        security_js = (
            project_root / "app/static/js/security.js"
        ).read_text(encoding="utf-8")
        scripts = "\n".join(
            (
                project_root / f"app/static/js/{name}"
            ).read_text(encoding="utf-8")
            for name in (
                "app.js",
                "dashboard.js",
                "waiter.js",
                "kitchen.js",
            )
        )
        templates = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                project_root / "app/templates/login.html",
                project_root / "app/templates/_active_context.html",
                project_root / "app/templates/restaurant_select.html",
            )
        )

        self.assertIn("X-CSRF-Token", security_js)
        self.assertIn("window.HostAISecurity.fetch", scripts)
        self.assertNotRegex(
            scripts,
            r"(?<!HostAISecurity\.)fetch\(",
        )
        self.assertNotIn("localStorage", security_js)
        self.assertIn('{% include "_csrf.html" %}', templates)
