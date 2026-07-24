import unittest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.database import get_db
from app.main import app


def _proxy_probe_app(*, trusted_hosts: list[str]):
    probe = FastAPI()

    @probe.get("/scope")
    def read_scope(request: Request):
        return {
            "client_ip": (
                request.client.host
                if request.client is not None
                else None
            ),
            "scheme": request.url.scheme,
        }

    return ProxyHeadersMiddleware(
        probe,
        trusted_hosts=trusted_hosts,
    )


class RuntimeValidationTests(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_trusted_proxy_populates_client_ip_and_https_scheme(self):
        proxy_app = _proxy_probe_app(trusted_hosts=["testclient"])
        with TestClient(proxy_app) as client:
            response = client.get(
                "/scope",
                headers={
                    "X-Forwarded-For": "203.0.113.15",
                    "X-Forwarded-Proto": "https",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "client_ip": "203.0.113.15",
                "scheme": "https",
            },
        )

    def test_untrusted_proxy_headers_are_ignored(self):
        proxy_app = _proxy_probe_app(
            trusted_hosts=["127.0.0.1"],
        )
        with TestClient(proxy_app) as client:
            response = client.get(
                "/scope",
                headers={
                    "X-Forwarded-For": "198.51.100.24",
                    "X-Forwarded-Proto": "https",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client_ip"], "testclient")
        self.assertEqual(response.json()["scheme"], "http")

    def test_request_logging_uses_validated_scope_client(self):
        with self.assertLogs("app.requests", level="INFO") as logs:
            with TestClient(app) as client:
                response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any(
                "client_ip=testclient" in message
                for message in logs.output
            )
        )

    def test_health_returns_service_unavailable_when_database_fails(self):
        class FailingSession:
            def execute(self, _statement):
                raise SQLAlchemyError("database unavailable")

            def rollback(self):
                return None

        def failing_database():
            yield FailingSession()

        app.dependency_overrides[get_db] = failing_database
        with TestClient(app) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["database"], "error")

    def test_security_helper_loads_before_consumer_scripts(self):
        with TestClient(app) as client:
            dashboard = client.get("/login")

        self.assertEqual(dashboard.status_code, 200)
        security_tag = (
            'src="http://testserver/static/js/security.js?v=34.0"'
        )
        self.assertIn(security_tag, dashboard.text)
        tag_start = dashboard.text.index(security_tag)
        tag_end = dashboard.text.index(">", tag_start)
        self.assertNotIn(
            "defer",
            dashboard.text[tag_start:tag_end],
        )

    def test_touch_target_rules_cover_shared_navigation(self):
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[1]
        shared_css = (
            project_root / "app/static/css/style.css"
        ).read_text(encoding="utf-8")
        dashboard_css = (
            project_root / "app/static/css/dashboard.css"
        ).read_text(encoding="utf-8")
        kitchen_css = (
            project_root / "app/static/css/kitchen.css"
        ).read_text(encoding="utf-8")

        self.assertIn(
            ".active-context-actions a,\n"
            ".active-context-actions button {\n"
            "    min-height: 48px;",
            shared_css,
        )
        self.assertIn(
            ".access-brand {\n"
            "    min-height: 44px;",
            shared_css,
        )
        self.assertIn(
            ".dashboard-brand {\n"
            "    min-height: 44px;",
            dashboard_css,
        )
        self.assertIn(
            ".kitchen-filters {\n"
            "        flex-wrap: wrap;\n"
            "        overflow-x: visible;",
            kitchen_css,
        )
