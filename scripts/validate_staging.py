"""Non-destructive HTTPS and session-security probe for HostAI staging."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


CSRF_PATTERN = re.compile(
    r'<meta\s+name="csrf-token"\s+content="([^"]+)"',
    re.IGNORECASE,
)
FORM_CSRF_PATTERN = re.compile(
    r'name="csrf_token"\s+value="([^"]+)"',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProbeResponse:
    status: int
    headers: object
    body: str
    url: str


class StagingProbe:
    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        password: str,
        restaurant_id: int,
        allow_http: bool,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" and not allow_http:
            raise ValueError("Staging validation requires an HTTPS base URL")
        self.base_url = base_url.rstrip("/") + "/"
        self.email = email
        self.password = password
        self.restaurant_id = restaurant_id
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self.origin = f"{parsed.scheme}://{parsed.netloc}"

    def run(self) -> None:
        health = self._request("/health")
        self._expect(health.status == 200, "health must return HTTP 200")
        health_payload = json.loads(health.body)
        self._expect(
            health_payload.get("database") == "ok",
            "health must confirm database connectivity",
        )
        self._report("health", "ok")

        login_page = self._request("/login")
        self._expect(login_page.status == 200, "login page must load")
        self._check_security_headers(login_page)
        self._check_session_cookie(login_page)
        form_csrf = self._extract_token(
            FORM_CSRF_PATTERN,
            login_page.body,
            "login form CSRF field",
        )
        self._report("login_page", "headers/cookie/form OK")

        login = self._request(
            "/login",
            method="POST",
            form={
                "email": self.email,
                "password": self.password,
                "csrf_token": form_csrf,
            },
        )
        self._expect(
            login.status == 200,
            "authenticated destination must load",
        )
        self._expect(
            urlparse(login.url).path != "/login",
            "login credentials were rejected",
        )
        csrf_token = self._extract_token(
            CSRF_PATTERN,
            login.body,
            "authenticated CSRF meta tag",
        )
        self._check_security_headers(login)
        self._report("login", "session rotation and redirect OK")

        protected_paths = (
            f"/api/orders/{self.restaurant_id}/-1/fulfill",
            (
                f"/api/dining/{self.restaurant_id}/sessions/"
                "-1/settle"
            ),
            (
                f"/api/dining/{self.restaurant_id}/settlements/"
                "-1/payments"
            ),
            f"/api/kitchen/{self.restaurant_id}/tickets/-1/start",
        )
        for path in protected_paths:
            response = self._request(
                path,
                method="POST",
                json_body={},
            )
            payload = json.loads(response.body)
            self._expect(
                response.status == 403
                and payload.get("error", {}).get("code")
                == "csrf_token_missing",
                f"CSRF middleware did not protect {path}",
            )
        self._report(
            "critical_mutations",
            "fulfillment/settlement/payment/kitchen protected",
        )

        context = self._request(
            "/api/access/active-restaurant",
            method="PUT",
            json_body={"restaurant_id": self.restaurant_id},
            csrf_token=csrf_token,
        )
        self._expect(
            context.status == 200,
            "valid CSRF restaurant switch failed",
        )
        self._report("csrf_valid_flow", "restaurant switch OK")

        logout = self._request(
            "/api/auth/logout",
            method="POST",
            csrf_token=csrf_token,
        )
        self._expect(logout.status == 204, "logout failed")
        current_user = self._request("/api/auth/me")
        self._expect(
            current_user.status == 401,
            "session remained authenticated after logout",
        )
        self._report("logout", "cookie invalidation OK")

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        form: dict[str, str] | None = None,
        json_body: dict | None = None,
        csrf_token: str | None = None,
    ) -> ProbeResponse:
        data = None
        headers = {"Accept": "application/json, text/html"}
        if form is not None:
            data = urlencode(form).encode("utf-8")
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded"
            )
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if method not in {"GET", "HEAD"}:
            headers["Origin"] = self.origin
        if csrf_token is not None:
            headers["X-CSRF-Token"] = csrf_token
        request = Request(
            urljoin(self.base_url, path.lstrip("/")),
            data=data,
            headers=headers,
            method=method,
        )
        try:
            response = self.opener.open(request, timeout=20)
        except HTTPError as exc:
            return ProbeResponse(
                exc.code,
                exc.headers,
                exc.read().decode("utf-8", errors="replace"),
                exc.geturl(),
            )
        with response:
            return ProbeResponse(
                response.status,
                response.headers,
                response.read().decode(
                    "utf-8",
                    errors="replace",
                ),
                response.geturl(),
            )

    def _check_security_headers(self, response: ProbeResponse) -> None:
        required = {
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "strict-origin-when-cross-origin",
        }
        for name, expected in required.items():
            self._expect(
                response.headers.get(name) == expected,
                f"missing or invalid {name}",
            )
        self._expect(
            bool(response.headers.get("content-security-policy")),
            "missing content-security-policy",
        )
        if self.origin.startswith("https://"):
            self._expect(
                bool(response.headers.get("strict-transport-security")),
                "missing HSTS under HTTPS",
            )

    def _check_session_cookie(self, response: ProbeResponse) -> None:
        cookie = response.headers.get("set-cookie", "").lower()
        for attribute in (
            "hostai_session=",
            "httponly",
            "samesite=lax",
            "path=/",
        ):
            self._expect(
                attribute in cookie,
                f"session cookie missing {attribute}",
            )
        if self.origin.startswith("https://"):
            self._expect(
                "secure" in cookie,
                "production session cookie is not Secure",
            )

    @staticmethod
    def _extract_token(
        pattern: re.Pattern[str],
        body: str,
        label: str,
    ) -> str:
        match = pattern.search(body)
        if match is None:
            raise RuntimeError(f"Missing {label}")
        return match.group(1)

    @staticmethod
    def _expect(condition: bool, message: str) -> None:
        if not condition:
            raise RuntimeError(message)

    @staticmethod
    def _report(check: str, result: str) -> None:
        print(f"{check}: {result}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate HostAI staging without creating business data."
        )
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("HOSTAI_STAGING_URL"),
    )
    parser.add_argument(
        "--email",
        default=os.getenv("HOSTAI_STAGING_EMAIL"),
    )
    parser.add_argument(
        "--password",
        default=os.getenv("HOSTAI_STAGING_PASSWORD"),
    )
    parser.add_argument(
        "--restaurant-id",
        type=int,
        default=int(
            os.getenv("HOSTAI_STAGING_RESTAURANT_ID", "0")
        ),
    )
    parser.add_argument(
        "--allow-http",
        action="store_true",
        help="Permit local HTTP testing; never use for real staging.",
    )
    arguments = parser.parse_args()
    if (
        not arguments.base_url
        or not arguments.email
        or not arguments.password
        or arguments.restaurant_id <= 0
    ):
        parser.error(
            "base URL, email, password and restaurant ID are required"
        )

    try:
        StagingProbe(
            base_url=arguments.base_url,
            email=arguments.email,
            password=arguments.password,
            restaurant_id=arguments.restaurant_id,
            allow_http=arguments.allow_http,
        ).run()
    except Exception as exc:
        print(f"staging validation failed: {exc}", file=sys.stderr)
        return 1
    print("staging validation: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
