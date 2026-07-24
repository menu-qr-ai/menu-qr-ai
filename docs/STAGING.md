# HostAI staging and runtime validation

This runbook deploys and validates HostAI without creating new business
features. Staging must use an isolated database and credentials that are not
shared with production.

## 1. Required architecture

- One Render Python web service.
- One Render PostgreSQL database in the same account and region.
- The web service uses the database internal URL.
- The PostgreSQL external network is disabled or restricted when it is not
  needed for an explicit maintenance window.
- Render terminates TLS and forwards traffic to the application port over its
  private runtime network.

Render documents that web service ports are not directly reachable from the
public internet and that its Python runtime sets `FORWARDED_ALLOW_IPS=*`.
Therefore Uvicorn may trust forwarded headers on Render. Do not copy this
wildcard to a Docker host or VM whose application port is publicly reachable.

References:

- https://render.com/docs/web-services
- https://render.com/docs/environment-variables
- https://render.com/docs/postgresql-creating-connecting
- https://www.uvicorn.org/settings/

## 2. Required environment

```dotenv
ENVIRONMENT=production
APP_URL=https://your-staging-host.onrender.com
CORS_ORIGINS=https://your-staging-host.onrender.com
DATABASE_URL=postgresql://...
SECRET_KEY=...
SESSION_MAX_AGE_SECONDS=43200
LOGIN_RATE_LIMIT_ATTEMPTS=5
LOGIN_RATE_LIMIT_WINDOW_SECONDS=900
LOG_LEVEL=INFO
```

`SECRET_KEY` must be unique to staging, at least 32 characters and must never
be committed. Generate one locally:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

HostAI fails fast in production when the secret is weak, `APP_URL` is not HTTPS
or CORS contains a wildcard.

Render supplies `PORT`, `RENDER_EXTERNAL_URL` and
`FORWARDED_ALLOW_IPS=*`. HostAI intentionally requires `APP_URL` to be explicit
so custom domains and CORS do not silently change when infrastructure changes.

## 3. Commands

Build:

```bash
pip install -r requirements.txt
```

Pre-deploy:

```bash
python -m alembic upgrade head
```

Start:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips "$FORWARDED_ALLOW_IPS" --no-access-log
```

`--no-access-log` evita que Uvicorn registre los tokens-capacidad presentes en
las rutas de QR y sesion de cliente. El middleware de HostAI mantiene un log de
peticiones estructurado con esos segmentos enmascarados. Aplica la misma
politica de omision o redaccion a cualquier proxy, CDN o plataforma que registre
la URL completa.

Health check path:

```text
/health
```

`/health` returns HTTP 503 when the database cannot execute its readiness
query. Configure this exact path in Render so a deployment with a broken
database connection is not promoted.

Do not run `app.utils.demo_seed` automatically in staging or production.

## 4. PostgreSQL reality validation

The automated CI job starts a real PostgreSQL service and sets
`HOSTAI_TEST_POSTGRES_URL`. The guarded integration suite:

- requires a dedicated database named `hostai_*_test`;
- upgrades every revision from 0001 through 0022 one by one;
- verifies the final tables, unique constraints and partial index;
- round-trips 0022 to 0018 and back;
- races fulfillment, settlement and payments with independent connections;
- verifies single effects and absence of overpayment.

To run it manually, create a disposable empty database:

```bash
HOSTAI_TEST_POSTGRES_URL=postgresql+psycopg2://user:password@host:5432/hostai_runtime_test \
python -m pytest -q tests/test_postgresql_runtime.py
```

The test drops and recreates only the `public` schema of the guarded test
database. Never point it at staging or production.

## 5. HTTPS/session probe

Create an active staging owner or manager account with access to the test
restaurant. The probe does not create orders, payments or operational data. It
validates:

- database health;
- HTTPS security headers;
- Secure, HttpOnly, SameSite and Path cookie attributes;
- login and session rotation;
- CSRF rejection on fulfillment, settlement, payment and kitchen actions;
- valid CSRF restaurant switching;
- logout and cookie invalidation.

PowerShell:

```powershell
$env:HOSTAI_STAGING_URL='https://your-staging-host.onrender.com'
$env:HOSTAI_STAGING_EMAIL='staging-owner@example.com'
$env:HOSTAI_STAGING_PASSWORD='set-outside-source-control'
$env:HOSTAI_STAGING_RESTAURANT_ID='1'
python scripts/validate_staging.py
```

Do not print, commit or persist the password in shell history used by shared
machines.

## 6. Proxy policy

Application code never parses `X-Forwarded-For`, `X-Forwarded-Proto` or
`X-Forwarded-Host`. It reads `request.client` and `request.url.scheme` from the
ASGI scope after Uvicorn has applied its trusted-proxy policy.

- Render: `FORWARDED_ALLOW_IPS=*` is acceptable because only Render's load
  balancer can reach the application port.
- Local development: retain `127.0.0.1`.
- Public VM or Docker port: use the exact proxy IP/CIDR; never use `*`.

Login and request audit logs use the validated scope client IP. They do not log
cookies, passwords, CSRF tokens or forwarded header contents. Customer QR and
session tokens are also redacted. Keep raw proxy access logs disabled or
sanitized because application middleware cannot rewrite logs emitted upstream.

## 7. Mobile QA matrix

Automated browser checks cover:

- 390x844 mobile portrait;
- 844x390 mobile landscape;
- 768x1024 tablet portrait;
- 1024x768 tablet landscape;
- login, restaurant selector, dashboard, waiter, kitchen and customer QR menu.

Acceptance checks are no horizontal document overflow, one page scroll,
touch targets of at least 44px and a working shared security helper. Physical
QA on iOS Safari, Android Chrome and a 10-inch tablet remains mandatory before
production because browser emulation cannot validate virtual keyboards, safe
areas, installed fonts or device performance.

## 8. Release gate and rollback

Before promotion:

```bash
python -m alembic current
python -m ruff check .
python -m pytest -q
python -m compileall -q app tests scripts
```

Confirm the revision is `0022_add_customer_qr_ordering_foundation`, `/health`
is 200 and the HTTPS probe passes. Validate that the QR route redirects to a
temporary customer session, that no capability token appears in application or
proxy logs, and that waiter approval is required before kitchen. If a deploy
fails, keep the previous application deploy; do not downgrade the production
database automatically. Database downgrade must be a reviewed operation
against a backup.
