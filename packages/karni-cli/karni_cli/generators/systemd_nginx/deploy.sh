#!/usr/bin/env bash
# Deploy {{slug}} on this server: its processes under systemd, behind nginx.
# `karni make deploy systemd-nginx` wrote this file, and it is yours to edit.
# deploy/README.md says how to prepare the server and what each step does.
#
#   sudo deploy/deploy.sh                    deploy this folder as a new release
#   sudo deploy/deploy.sh --rollback         switch back to the release before the current one
#   sudo deploy/deploy.sh --rollback <id>    switch to that release
#   deploy/deploy.sh --list                  the releases on this server, the current one marked
#
# It touches only its own paths: $ROOT (releases/, shared/, current), the units
# <app>-<unit>.service in $SYSTEMD_DIR, and <app>.conf in nginx's sites-available with its
# link in sites-enabled. It writes $ROOT/shared/.env once, from deploy/env.example, and
# never writes over it or deletes it afterwards. It runs `nginx -t` before every reload,
# and takes its own vhost out again when the test fails. Running it again is safe, and
# every step that fails stops the run with a message.
set -euo pipefail

# The defaults `karni make deploy systemd-nginx` wrote. DEPLOY_<NAME> in the environment
# replaces one for a run (sudo DEPLOY_KEEP=10 deploy/deploy.sh).
APP="${DEPLOY_APP:-{{slug}}}"
DOMAIN="${DEPLOY_DOMAIN:-{{domain}}}"
ROOT="${DEPLOY_ROOT:-{{root}}}"
RUN_AS="${DEPLOY_RUN_AS:-{{user}}}"
KEEP="${DEPLOY_KEEP:-{{keep}}}"
CERT="${DEPLOY_CERT:-{{cert}}}"
CERT_KEY="${DEPLOY_CERT_KEY:-{{cert_key}}}"
UNITS="${DEPLOY_UNITS:-{{units}}}"
PYTHON="${DEPLOY_PYTHON:-python3}"
SYSTEMD_DIR="${DEPLOY_SYSTEMD_DIR:-/etc/systemd/system}"
NGINX_DIR="${DEPLOY_NGINX_DIR:-/etc/nginx}"
SOCKET="${DEPLOY_SOCKET:-/run/$APP/gunicorn.sock}"
HEALTH_PATH="${DEPLOY_HEALTH_PATH:-{{ready_path}}}"
HEALTH_TRIES="${DEPLOY_HEALTH_TRIES:-30}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
LOCK=""
trap 'rm -rf "$TMP"; if [ -n "$LOCK" ]; then rmdir "$LOCK" 2>/dev/null || true; fi' EXIT
RELEASE=""
code=""

say() { printf '\n== %s\n' "$*"; }
fail() {
  printf '\ndeploy.sh: %s\n' "$*" >&2
  exit 1
}
need() { command -v "$1" >/dev/null 2>&1 || fail "$1 is not installed. $2"; }
as_root() { [ "$(id -u)" = 0 ]; }

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
}

# Runs a command as the user the units run as (root runs it as RUN_AS, anyone else as
# themselves), so the files it writes belong to the site, not to root.
as_user() {
  if as_root && [ "$RUN_AS" != root ]; then
    if command -v runuser >/dev/null 2>&1; then
      runuser -u "$RUN_AS" -- "$@"
    else
      sudo -u "$RUN_AS" -- "$@"
    fi
  else
    "$@"
  fi
}

# manage <release dir> <arguments>: that release's manage.py, with the server's .env.
manage() {
  local dir="$1"
  shift
  (cd "$dir" && as_user ./.venv/bin/python manage.py "$@")
}

# One deploy or rollback at a time.
lock() {
  mkdir -p "$ROOT"
  mkdir "$ROOT/.deploy.lock" 2>/dev/null || fail "another deploy.sh runs in $ROOT (or one was killed: then remove $ROOT/.deploy.lock)."
  LOCK="$ROOT/.deploy.lock"
}

# The release folders in $ROOT/releases, oldest first: with `all`, those whose build
# stopped half way too.
release_folders() {
  [ -d "$ROOT/releases" ] || return 0
  local path name
  for path in "$ROOT"/releases/*; do
    [ -d "$path" ] || continue
    name="$(basename "$path")"
    case "$name" in
      [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]*)
        if [ "${1:-}" = all ] || [ -f "$path/.built" ]; then
          printf '%s\n' "$name"
        fi
        ;;
    esac
  done | sort
}

# The releases whose build finished, oldest first.
releases() { release_folders; }

# The newest release before the current one that answered its health check: what
# --rollback goes back to.
last_good() {
  local cur id found=""
  cur="$(current)"
  for id in $(releases); do
    [ "$id" = "$cur" ] && break
    if [ -f "$ROOT/releases/$id/.live" ]; then
      found="$id"
    fi
  done
  printf '%s' "$found"
}

current() {
  if [ -L "$ROOT/current" ]; then
    basename "$(readlink "$ROOT/current")"
  fi
}

# render <template> <file>: the template with this server's values in place of @NAME@.
render() {
  local app_id
  app_id="$(printf '%s' "$APP" | tr -c 'A-Za-z0-9_' '_')"
  sed -e "s|@APP_ID@|$app_id|g" -e "s|@APP@|$APP|g" -e "s|@DOMAIN@|$DOMAIN|g" -e "s|@ROOT@|$ROOT|g" \
    -e "s|@RUN_AS@|$RUN_AS|g" -e "s|@CERT@|$CERT|g" -e "s|@CERT_KEY@|$CERT_KEY|g" \
    "$1" >"$2"
  if grep -q '@[A-Z_]*@' "$2"; then
    fail "$1 names $(grep -o '@[A-Z_]*@' "$2" | head -n 1), a value deploy.sh does not know."
  fi
}

check_values() {
  local name value
  for name in APP DOMAIN ROOT RUN_AS CERT CERT_KEY; do
    eval "value=\$$name"
    [ -n "$value" ] || fail "$name is empty. Set it at the top of deploy/deploy.sh."
    case "$value" in
      *'|'* | *' '*) fail "$name is '$value': a value here has no space and no |." ;;
    esac
  done
  case "$ROOT" in
    /*) ;;
    *) fail "ROOT is '$ROOT': give an absolute path, such as /srv/$APP." ;;
  esac
  case "$KEEP" in
    '' | *[!0-9]*) fail "KEEP is '$KEEP': give the number of releases to keep, 2 or more." ;;
  esac
  [ "$KEEP" -ge 2 ] || fail "KEEP is $KEEP: keep 2 or more releases, so there is one to roll back to."
}

preflight() {
  say "preflight"
  check_values
  need "$PYTHON" "Install Python 3.12 or later (python3 and python3-venv), or set DEPLOY_PYTHON."
  need nginx "Install nginx (apt install nginx)."
  need systemctl "This script runs units under systemd."
  need curl "Install curl: the health check asks the web process through its socket."
  [ -r "$CERT" ] || fail "no certificate at $CERT. Get one first, for example
  sudo certbot certonly --nginx -d $DOMAIN
or set CERT and CERT_KEY at the top of deploy/deploy.sh to the certificate you have."
  [ -r "$CERT_KEY" ] || fail "no certificate key at $CERT_KEY (see CERT_KEY at the top of deploy/deploy.sh)."
  if ! nginx -t >"$TMP/nginx-before.log" 2>&1; then
    cat "$TMP/nginx-before.log" >&2
    fail "nginx -t fails before this deploy changed anything. Fix that first: nothing was changed."
  fi
  echo "   nginx -t passes, the certificate is there"
}

shared() {
  mkdir -p "$ROOT/releases" "$ROOT/shared/media" "$ROOT/shared/static"{{web_dir}}
  if [ ! -e "$ROOT/shared/.env" ]; then
    [ -f "$SRC/deploy/env.example" ] || fail "$SRC/deploy/env.example is missing: run karni make deploy systemd-nginx in the project."
    (umask 077 && cp "$SRC/deploy/env.example" "$ROOT/shared/.env")
    if as_root; then
      chown "root:$RUN_AS" "$ROOT/shared/.env"
      chmod 640 "$ROOT/shared/.env"
    fi
    fail "wrote $ROOT/shared/.env from deploy/env.example. Fill in every empty value (SECRET_KEY, KARNI_ADMIN_PATH, the database password, email), then run deploy.sh again. It never writes over that file."
  fi
  echo "   $ROOT/shared/.env is there, left as it is"
  if as_root; then
    chown -R "$RUN_AS:$RUN_AS" "$ROOT/shared/media" "$ROOT/shared/static"{{web_dir}}
  fi
}

# Copies the project into a new release folder, without what never runs on the server:
# version control, virtual environments, local data and the .env files.
copy_source() {
  "$PYTHON" - "$SRC" "$1" <<'PY'
import shutil
import sys
from pathlib import Path

source, target = Path(sys.argv[1]), Path(sys.argv[2])
TOP = {".git", ".venv", "venv", "data", ".karni", "node_modules"}
ANYWHERE = {"__pycache__", "node_modules", ".pytest_cache", ".ruff_cache", ".mypy_cache"}


def ignore(folder: str, names: list[str]) -> list[str]:
    top = Path(folder) == source
    return [
        name
        for name in names
        if name in ANYWHERE
        or name.endswith(".pyc")
        or name == ".env"
        or name.startswith(".env.")
        or (top and name in TOP)
    ]


shutil.copytree(source, target, ignore=ignore, symlinks=True, dirs_exist_ok=True)
PY
}

{{games_functions}}build() {
  local id rev rel old
  [ -f "$SRC/manage.py" ] || fail "$SRC has no manage.py: run deploy/deploy.sh from the project's deploy/ folder."
  id="$(date -u +%Y%m%d%H%M%S)"
  rev=""
  if command -v git >/dev/null 2>&1 && git -C "$SRC" rev-parse --short HEAD >/dev/null 2>&1; then
    rev="$(git -C "$SRC" rev-parse --short HEAD)"
    id="$id-$rev"
  fi
  rel="$ROOT/releases/$id"
  [ ! -e "$rel" ] || fail "release $id exists already. Wait a second and run deploy.sh again."
  for old in $(release_folders all); do
    if [ ! -f "$ROOT/releases/$old/.built" ]; then
      rm -rf "${ROOT:?}/releases/$old"
      echo "   removed $old, whose build stopped half way"
    fi
  done
  say "release $id"
  mkdir -p "$rel"
  copy_source "$rel"
  printf '%s\n' "$id" >"$rel/REVISION"
  echo "   copied $SRC"

  say "python environment"
  "$PYTHON" -m venv "$rel/.venv"
  "$rel/.venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip
  "$rel/.venv/bin/python" -m pip install --quiet --disable-pip-version-check "$rel"
  ln -s "$ROOT/shared/.env" "$rel/.env"
  echo "   installed the project's dependencies into $rel/.venv"

  say "deploy checks, migrations, static files"
  manage "$rel" karni_check --deploy --no-cache
  manage "$rel" migrate --noinput
  manage "$rel" collectstatic --noinput -v 0
{{seed_step}}{{games_step}}  touch "$rel/.built"
  RELEASE="$id"
}

install_units() {
  local release="$1" unit template target changed=""
  mkdir -p "$SYSTEMD_DIR"
  for unit in $UNITS; do
    template="$release/deploy/$unit.service"
    [ -f "$template" ] || fail "$template is missing: run karni make deploy systemd-nginx --force in the project."
    target="$SYSTEMD_DIR/$APP-$unit.service"
    render "$template" "$TMP/$unit.service"
    if ! cmp -s "$TMP/$unit.service" "$target"; then
      install -m 644 "$TMP/$unit.service" "$target"
      changed=1
    fi
  done
  if [ -n "$changed" ]; then
    systemctl daemon-reload
  fi
  for unit in $UNITS; do
    systemctl enable --quiet "$APP-$unit.service"
  done
}

healthy() {
  local tries=0
  while [ "$tries" -lt "$HEALTH_TRIES" ]; do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 --unix-socket "$SOCKET" \
      -H "Host: $DOMAIN" -H "X-Forwarded-Proto: https" "http://localhost$HEALTH_PATH" || true)"
    [ "$code" = 200 ] && return 0
    tries=$((tries + 1))
    sleep 1
  done
  return 1
}

install_vhost() {
  local release="$1" available enabled backup="" was_enabled="" outcome
  available="$NGINX_DIR/sites-available/$APP.conf"
  enabled="$NGINX_DIR/sites-enabled/$APP.conf"
  render "$release/deploy/nginx.conf" "$TMP/nginx.conf"
  if [ -L "$enabled" ] && cmp -s "$TMP/nginx.conf" "$available"; then
    echo "   nginx: the vhost is unchanged"
    return 0
  fi
  mkdir -p "$NGINX_DIR/sites-available" "$NGINX_DIR/sites-enabled"
  if [ -f "$available" ]; then
    backup="$TMP/nginx.conf.before"
    cp "$available" "$backup"
  fi
  if [ -L "$enabled" ]; then
    was_enabled=1
  fi
  install -m 644 "$TMP/nginx.conf" "$available"
  ln -sfn "$available" "$enabled"
  if nginx -t >"$TMP/nginx-test.log" 2>&1; then
    systemctl reload nginx
    echo "   nginx: vhost installed, nginx -t passed, nginx reloaded"
    return 0
  fi
  cat "$TMP/nginx-test.log" >&2
  if [ -n "$backup" ] && [ -n "$was_enabled" ]; then
    install -m 644 "$backup" "$available"
    outcome="the previous vhost is back in place"
  else
    rm -f "$enabled"
    if [ -n "$backup" ]; then
      install -m 644 "$backup" "$available"
    fi
    outcome="the vhost is unhooked (its link in sites-enabled is removed)"
  fi
  if nginx -t >/dev/null 2>&1; then
    outcome="$outcome, and nginx -t passes again, so the other sites keep working"
  else
    outcome="$outcome, but nginx -t still fails, for a reason outside this site"
  fi
  fail "nginx -t refused deploy/nginx.conf: $outcome. nginx was not reloaded, and the app runs the new release."
}

# activate <release id>: point current at it, install its units and vhost, restart.
activate() {
  local id="$1" rel
  rel="$ROOT/releases/$id"
  say "switching to $id"
  ln -sfn "releases/$id" "$ROOT/current.next"
  "$PYTHON" -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' "$ROOT/current.next" "$ROOT/current"
  install_units "$rel"
  local unit
  for unit in $UNITS; do
    systemctl restart "$APP-$unit.service"
  done
  if ! healthy; then
    if command -v journalctl >/dev/null 2>&1; then
      journalctl -u "$APP-web.service" -n 40 --no-pager >&2 || true
    fi
    local back="There is no earlier release to go back to." good
    good="$(last_good)"
    if [ -n "$good" ]; then
      back="sudo deploy/deploy.sh --rollback switches back to $good."
    fi
    fail "the web process did not answer $HEALTH_PATH with 200 (last answer: ${code:-none}). $back"
  fi
  touch "$rel/.live"
  echo "   $APP-web answers $HEALTH_PATH with 200"
  say "nginx"
  install_vhost "$rel"
}

prune() {
  local count excess old cur good
  cur="$(current)"
  good="$(last_good)"
  count="$(releases | wc -l | tr -d ' ')"
  excess=$((count - KEEP))
  [ "$excess" -gt 0 ] || return 0
  say "keeping the newest $KEEP releases"
  for old in $(releases | head -n "$excess"); do
    if [ "$old" = "$cur" ] || [ "$old" = "$good" ]; then
      continue
    fi
    rm -rf "${ROOT:?}/releases/$old"
    echo "   removed release $old"
  done
}

list() {
  local cur id
  cur="$(current)"
  if [ -z "$(releases)" ]; then
    echo "No releases in $ROOT/releases yet."
    return 0
  fi
  for id in $(releases); do
    if [ "$id" = "$cur" ]; then
      echo "* $id (current)"
    elif [ -f "$ROOT/releases/$id/.live" ]; then
      echo "  $id"
    else
      echo "  $id (never answered its health check)"
    fi
  done
}

rollback() {
  local target="${1:-}" cur
  cur="$(current)"
  [ -n "$cur" ] || fail "no current release in $ROOT: nothing to roll back."
  if [ -z "$target" ]; then
    target="$(last_good)"
    [ -n "$target" ] || fail "no release before $cur answered its health check: nothing to roll back to (deploy.sh --list shows the releases)."
  fi
  [ -f "$ROOT/releases/$target/.built" ] || fail "no release $target in $ROOT/releases (deploy.sh --list shows them)."
  [ "$target" != "$cur" ] || fail "$target is the current release already."
  say "rolling back from $cur to $target"
  manage "$ROOT/releases/$target" collectstatic --noinput -v 0
{{games_rollback}}  activate "$target"
  say "rolled back to $target"
  echo "Migrations that $cur applied stay in the database. If $target cannot run with them,"
  echo "reverse them with $cur's code first (manage.py migrate <app> <migration>), then roll back."
}

main() {
  case "${1:-}" in
    "")
      preflight
      lock
      shared
      build
      activate "$RELEASE"
      prune
      say "deployed $RELEASE"
      echo "https://$DOMAIN/"
      ;;
    --rollback)
      preflight
      lock
      rollback "${2:-}"
      ;;
    --list)
      list
      ;;
    -h | --help)
      usage
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
