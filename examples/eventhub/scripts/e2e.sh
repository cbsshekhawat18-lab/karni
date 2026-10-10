#!/usr/bin/env bash
# The end-to-end run, locally and in CI: build, migrate, seed, start the stack,
# run Playwright, stop the stack. Needs the project .venv, Redis on REDIS_URL
# and frontend/node_modules (npm ci). Exit code is Playwright's.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-.venv/bin/python}
PORT=${E2E_API_PORT:-8431}
export DJANGO_SETTINGS_MODULE=config.settings
export KARNI_API_PROXY="http://127.0.0.1:$PORT"   # vite preview proxies /api here
export E2E_API_URL="http://127.0.0.1:$PORT"       # the spec posts the webhook here
# The browser's origin must be a CSRF-trusted origin (derived from this setting).
export KARNI_FRONTEND_URL="http://127.0.0.1:${E2E_WEB_PORT:-4173}"

(cd frontend && npm run build)
"$PY" manage.py migrate --noinput
# `karni seed --reset` resets the project's own tables; module tables (payments,
# webhook events) would otherwise carry over between runs and replay-protect the
# very webhook the suite sends. Start from nothing.
"$PY" manage.py flush --noinput
"$PY" manage.py karni_seed --reset --seed 42

"$PY" manage.py runserver "127.0.0.1:$PORT" --noreload > .notes-e2e-django.log 2>&1 &
DJANGO=$!
"$PY" -m celery -A config worker --loglevel=info --pool=solo > .notes-e2e-worker.log 2>&1 &
WORKER=$!
trap 'kill $DJANGO $WORKER 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:$PORT/health/ready/ > /dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:$PORT/health/ready/

cd frontend && npx playwright test "$@"
