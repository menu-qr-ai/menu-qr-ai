#!/usr/bin/env bash
# Render start command (free plan: no pre-deploy hook, no shell).
set -euo pipefail

# Render provides the public URL; an explicit APP_URL (custom domain) wins.
export APP_URL="${APP_URL:-${RENDER_EXTERNAL_URL:?RENDER_EXTERNAL_URL is not set}}"
export CORS_ORIGINS="${CORS_ORIGINS:-$APP_URL}"

python -m alembic upgrade head
python -m app.utils.deploy_bootstrap

# --no-access-log: QR and customer-session URLs carry bearer tokens.
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-10000}" \
    --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" --no-access-log
