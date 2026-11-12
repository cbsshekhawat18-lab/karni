#!/usr/bin/env bash
# The demo as it runs on the host, checked from outside: production settings
# (DJANGO_ENV=prod, DEBUG off, a generated SECRET_KEY, DEMO_MODE on), a fresh
# SQLite database, the deploy gate and the exact start command, then curl.
#
#   (cd frontend && npm ci && npm run build)    # the React app it serves
#   PORT=8950 ./scripts/smoke.sh
#
# Needs python on PATH with the project's packages (pyproject.toml) and curl.
# Requests carry X-Forwarded-Proto: https, as the host's proxy sends it, since
# production redirects plain http. CI runs this (.github/workflows/ci.yml).
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=${PORT:-8950}
BASE="http://127.0.0.1:$PORT"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/shop-demo-smoke.XXXXXX")

export DJANGO_ENV=prod DEBUG=False DEMO_MODE=True
SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(50))')
export SECRET_KEY
export ALLOWED_HOSTS=127.0.0.1
export CSRF_TRUSTED_ORIGINS="https://127.0.0.1:$PORT" KARNI_FRONTEND_URL="https://127.0.0.1:$PORT"
export DATABASE_URL="sqlite:///$WORK/db.sqlite3" STATIC_ROOT="$WORK/static" MEDIA_ROOT="$WORK/media"
export KARNI_CACHE=locmem CACHE_URL="filecache://$WORK/cache"
export CELERY_TASK_ALWAYS_EAGER=True KARNI_PAYMENTS_PROVIDER=test
export KARNI_READYZ_CHECKS=karni.health.checks.check_database,karni.health.checks.check_cache
export KARNI_HEALTH_CHECKS=$KARNI_READYZ_CHECKS
# A second account, to check that every account but the demo one is read-only.
export KARNI_SEED_LOGINS='{"customer@example.com": ["customer"]}'
export HOST=127.0.0.1 PORT WEB_CONCURRENCY=${WEB_CONCURRENCY:-2}

python manage.py collectstatic --noinput -v 0  # the image does this when it is built
python -m karni.deploy.entrypoint sh scripts/start.sh > "$WORK/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true; wait $SERVER 2>/dev/null || true; rm -rf "$WORK"' EXIT

get() { curl -sS -H "X-Forwarded-Proto: https" "$@"; }
status() { curl -sS -o /dev/null -w '%{http_code}' -H "X-Forwarded-Proto: https" "$@"; }
field() { python -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }
fail() { echo "FAIL: $*"; echo "--- server log"; tail -40 "$WORK/server.log"; exit 1; }
pass() { echo "ok    $*"; }

for _ in $(seq 1 90); do
  [ "$(status "$BASE/healthz" 2>/dev/null || true)" = 200 ] && break
  kill -0 $SERVER 2>/dev/null || fail "the server stopped while starting"
  sleep 1
done
[ "$(status "$BASE/readyz")" = 200 ] || fail "/readyz"
pass "started: deploy checks, migrate, seed, gunicorn on :$PORT"

page=$(get "$BASE/")
grep -q 'name="demo-login-email" content="demo@example.com"' <<<"$page" || fail "sign-in page: no demo email"
grep -q 'name="demo-login-password" content="karni-password"' <<<"$page" || fail "sign-in page: no demo password"
grep -q '/assets/index-' <<<"$page" || fail "sign-in page: not the React build"
[ "$(status "$BASE/orders/some-deep-link")" = 200 ] || fail "a deep link of the app"
asset=$(grep -o '/assets/index-[^"]*\.js' <<<"$page" | head -1)
get -D - -o /dev/null "$BASE$asset" | grep -qi 'cache-control: max-age=315360000' || fail "$asset is not cached for a year"
grep -q 'demo@example.com' <<<"$(get "$BASE/admin/login/")" || fail "admin sign-in page: no demo login"
pass "sign-in pages show the demo login, the app and its files are served"

[ "$(get "$BASE/api/products/" | field count)" = 40 ] || fail "anonymous read of /api/products/"
pass "anonymous read: 40 products"

body=$(get -X POST -H 'Content-Type: application/json' -d '{"name": "Smoke"}' "$BASE/api/categories/")
[ "$(field code <<<"$body")" = demo_read_only ] || fail "anonymous write was not refused: $body"
[ "$(status -X POST -H 'Content-Type: application/json' -d '{"email": "a@example.com", "password": "x"}' "$BASE/api/auth/register/")" != 201 ] || fail "sign-up is open"
pass "anonymous write refused, sign-up closed"

login() { get -X POST -H 'Content-Type: application/json' -d "{\"email\": \"$1\", \"password\": \"karni-password\"}" "$BASE/api/auth/login/" | field access; }
CUSTOMER=$(login customer@example.com) || fail "customer sign-in"
get -X POST -H "Authorization: Bearer $CUSTOMER" -H 'Content-Type: application/json' \
  -d "{\"version\": \"$(get -H "Authorization: Bearer $CUSTOMER" "$BASE/api/auth/terms/" | field version)\"}" \
  "$BASE/api/auth/terms/accept/" > /dev/null
[ "$(status -H "Authorization: Bearer $CUSTOMER" "$BASE/api/orders/")" = 200 ] || fail "customer read"
body=$(get -X POST -H "Authorization: Bearer $CUSTOMER" -H 'Content-Type: application/json' -d '{}' "$BASE/api/carts/")
[ "$(field code <<<"$body")" = demo_read_only ] || fail "customer write was not refused: $body"
pass "another account signs in and reads, its write is refused"

DEMO=$(login demo@example.com) || fail "demo sign-in"
body=$(get -X POST -H "Authorization: Bearer $DEMO" -H 'Content-Type: application/json' -d '{"name": "Smoke category"}' "$BASE/api/categories/")
[ "$(field name <<<"$body")" = "Smoke category" ] || fail "demo write: $body"
body=$(get -X POST -H "Authorization: Bearer $DEMO" -H 'Content-Type: application/json' \
  -d '{"old_password": "karni-password", "new_password": "another-password-1"}' "$BASE/api/auth/password/change/")
[ "$(field code <<<"$body")" = demo_account_locked ] || fail "demo password change was not refused: $body"
[ -n "$(login demo@example.com)" ] || fail "demo sign-in after the refused change"
pass "the demo account writes, and cannot change its password"

echo "PASS: the demo serves, signs in and enforces its write rule"
