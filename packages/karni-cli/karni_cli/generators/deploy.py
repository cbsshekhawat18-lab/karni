"""``karni make deploy compose``: the production stack, as files the project owns.

It writes three files and edits two ignore files:

* ``docker-compose.prod.yml``: a one-shot ``release`` service (the deploy
  checks, ``migrate``, ``collectstatic``, the web server's files), ``django``
  (gunicorn with uvicorn workers), Celery ``worker`` and ``beat``, ``caddy``
  (TLS, static and media files, the staff app, the proxy), ``db``
  (PostgreSQL), ``redis`` and ``backup``. Health checks on every long-running
  service, restart policies, memory limits, log rotation, named volumes and no
  bind mount of source.
* ``Caddyfile``: the web front. Caddy reads it from the shared volume, where
  the release step publishes it from the image (``manage.py
  karni_publish_web``), together with the built staff app and the security
  headers Django sends.
* ``.env.prod.example``: every production value, to copy to ``.env.prod``.
* ``.gitignore`` and ``.dockerignore`` get ``.env.prod`` when they lack it, so
  the secrets are neither committed nor copied into the image.

Everything the files run lives in karni (:mod:`karni.deploy`) and in the
project's Dockerfile targets (``prod``, ``staff-app``, ``backup``), so the
generator writes configuration only. ``karni new`` runs it with the defaults.

Choices are flags, defaults suit most projects: the staff app at ``/app/``
(``--app-path``), on its own host (``--app-domain``) or not served
(``--no-app``), and ``--no-celery``, ``--no-backups``, ``--no-db`` (a managed
database) and ``--no-redis`` (a managed Redis). Hosts, ports, sizes and image
tags are variables in ``.env.prod``. Every file is the project's to edit, and
``--force`` writes them again.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

import typer

from karni_cli.generators.core import DRY_RUN_OPTION, FORCE_OPTION, Workspace, project_workspace
from karni_cli.project import CliError

NAME = "deploy"
SUMMARY = "Write the production stack: docker-compose.prod.yml, the Caddyfile, .env.prod.example."

TARGETS = ("compose",)
COMPOSE_FILE = "docker-compose.prod.yml"
CADDYFILE = "Caddyfile"
ENV_EXAMPLE = ".env.prod.example"
ENV_FILE = ".env.prod"
DEFAULT_APP_PATH = "/app/"
DEFAULT_DOMAIN = "example.com"
#: Where caddy sees the shared volume, and the release step's web root inside it.
VOLUME = "/srv/data"
WEB_ROOT = f"{VOLUME}/web"

_HOST = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
_APP_PATH = re.compile(r"^/([A-Za-z0-9_-]+/)*$")
_TARGET = re.compile(r"^\s*FROM\s+\S+\s+AS\s+(\S+)", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Options:
    """What the stack contains. ``app_path`` is ``None`` when no staff app is served."""

    slug: str
    domain: str = DEFAULT_DOMAIN
    app_path: str | None = DEFAULT_APP_PATH
    app_domain: str | None = None
    celery: bool = True
    backups: bool = True
    db: bool = True
    redis: bool = True
    auth_mode: str = "jwt"
    #: The path django's health check asks: ``/readyz`` when the project mounts
    #: ``karni.health.probe_urls`` (every new project does), else ``/health/``.
    ready_path: str = "/health/"

    @property
    def app(self) -> bool:
        return self.app_domain is not None or self.app_path is not None

    @property
    def app_base(self) -> str:
        """The Vite base the staff app is built with."""
        return "/" if self.app_domain or not self.app_path else self.app_path

    @property
    def app_url(self) -> str:
        if self.app_domain:
            return f"https://{self.app_domain}"
        return f"https://{self.domain}{(self.app_path or '/').rstrip('/')}"


def _block(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _depends(options: Options, *, release: bool = True, django: bool = False) -> list[str]:
    entries: list[tuple[str, str]] = []
    if release:
        entries.append(("release", "service_completed_successfully"))
    if django:
        entries.append(("django", "service_healthy"))
    if options.db and not django:
        entries.append(("db", "service_healthy"))
    if options.redis and not django:
        entries.append(("redis", "service_healthy"))
    if not entries:
        return []
    out = ["    depends_on:"]
    for service, condition in entries:
        out += [f"      {service}:", f"        condition: {condition}"]
    return out


def _django_probe(options: Options) -> list[str]:
    command = '"python", "-m", "karni.deploy.healthcheck", "--quiet"'
    if options.ready_path != "/health/":
        command = f'"python", "-m", "karni.deploy.healthcheck", "http://127.0.0.1:8000{options.ready_path}", "--quiet"'
    return [f'      test: ["CMD", {command}]']


def _limits(variable: str, default: str) -> list[str]:
    return [
        "    deploy:",
        "      resources:",
        "        limits:",
        f"          memory: ${{{variable}:-{default}}}",
    ]


def compose(options: Options) -> str:
    """The text of ``docker-compose.prod.yml``."""
    slug = options.slug
    services = ["release", "django"]
    if options.celery:
        services += ["worker", "beat"]
    services.append("caddy")
    if options.db:
        services.append("db")
    if options.redis:
        services.append("redis")
    if options.backups:
        services.append("backup")
    publish = "python manage.py karni_publish_web --root /data/web"
    if not options.app:
        publish += ' --app ""'
    out = [
        f"# Production stack for {slug}. `karni make deploy compose` wrote this file, and it",
        "# is yours to edit. docs/deploy.md walks through a server, DNS, updates, rollback",
        "# and restore.",
        "#",
        f"#   cp {ENV_EXAMPLE} {ENV_FILE}          # fill in every value, never commit it",
        f"#   docker compose -f {COMPOSE_FILE} --env-file {ENV_FILE} up -d --build",
        "#",
        f"# Services: {', '.join(services)}.",
        "# Every container from the prod image runs `karni check --deploy` before its",
        "# command and refuses to start while it fails (E520). The image carries the",
        "# code, named volumes hold the data, and nothing binds source from the host.",
        "",
        "x-logging: &logging",
        "  driver: json-file",
        "  options:",
        '    max-size: "10m"',
        '    max-file: "5"',
        "",
        "# The production image (the Dockerfile's prod target), shared by every app service.",
        "x-app: &app",
        f"  image: ${{KARNI_IMAGE:-{slug}}}:${{KARNI_TAG:-latest}}",
        "  build:",
        "    context: .",
        "    target: prod",
        "    args:",
        "      KARNI_SRC: ${KARNI_SRC:-}",
        "      KARNI_UI_TARBALL: ${KARNI_UI_TARBALL:-}",
        f"      KARNI_APP_PATH: {options.app_base}",
        '  entrypoint: ["python", "-m", "karni.deploy.entrypoint"]',
        f"  env_file: {ENV_FILE}",
        "  restart: unless-stopped",
        "  volumes:",
        "    - app_data:/data",
        "  logging: *logging",
        "",
        "services:",
        "  # Runs to completion before the others start: the deploy checks, the",
        "  # migrations, collectstatic, then the Caddyfile, the security headers and",
        "  # the staff app into /data/web for caddy. If it fails, nothing starts.",
        "  release:",
        "    <<: *app",
        '    restart: "no"',
        "    command:",
        "      - sh",
        "      - -c",
        "      - >-",
        "        python manage.py migrate --noinput",
        "        && python manage.py collectstatic --noinput -v 0",
        f"        && {publish}",
        *_depends(options, release=False),
        *_limits("KARNI_DJANGO_MEMORY", "768M"),
        "",
        "  django:",
        "    <<: *app",
        "    command:",
        '      ["gunicorn", "config.asgi:application", "-k", "uvicorn_worker.UvicornWorker",',
        '       "-b", "0.0.0.0:8000", "--graceful-timeout", "30"]',
        "    environment:",
        "      # gunicorn worker processes: about two per CPU core.",
        "      WEB_CONCURRENCY: ${WEB_CONCURRENCY:-2}",
        *_depends(options),
        "    healthcheck:",
        f"      # {options.ready_path} with an allowed Host and X-Forwarded-Proto: https, as caddy asks.",
        *_django_probe(options),
        "      interval: 10s",
        "      timeout: 5s",
        "      retries: 6",
        "      start_period: 60s",
        "    stop_grace_period: 30s",
        *_limits("KARNI_DJANGO_MEMORY", "768M"),
        "",
    ]
    if options.celery:
        out += [
            "  worker:",
            "    <<: *app",
            "    command:",
            '      ["celery", "-A", "config", "worker", "-l", "info",',
            '       "--concurrency", "${KARNI_WORKER_CONCURRENCY:-2}"]',
            *_depends(options),
            "    healthcheck:",
            "      test:",
            '        ["CMD-SHELL", "celery -A config inspect ping -d celery@$$HOSTNAME -t 10 > /dev/null"]',
            "      interval: 30s",
            "      timeout: 30s",
            "      retries: 3",
            "      start_period: 60s",
            "    # A running task gets this long to finish when the worker stops.",
            "    stop_grace_period: 60s",
            *_limits("KARNI_WORKER_MEMORY", "768M"),
            "",
            "  # One beat only: two would send every scheduled task twice. Never scale it.",
            "  beat:",
            "    <<: *app",
            '    command: ["celery", "-A", "config", "beat", "-l", "info", "--pidfile="]',
            *_depends(options),
            "    healthcheck:",
            "      # beat has no port: healthy once it runs past the deploy gate.",
            "      test:",
            '        ["CMD", "python", "-m", "karni.deploy.healthcheck", "--process", "beat", "--quiet"]',
            "      interval: 30s",
            "      timeout: 5s",
            "      retries: 3",
            "      start_period: 60s",
            *_limits("KARNI_BEAT_MEMORY", "256M"),
            "",
        ]
    caddy_env = ["      DOMAIN: ${DOMAIN:?set DOMAIN in .env.prod}"]
    if options.app_domain:
        caddy_env.append("      APP_DOMAIN: ${APP_DOMAIN:?set APP_DOMAIN in .env.prod}")
    if options.app and options.app_base == "/" and not options.app_domain:
        caddy_env.append(
            "      KARNI_ADMIN_PATH: ${KARNI_ADMIN_PATH:?set KARNI_ADMIN_PATH in .env.prod}"
        )
    out += [
        "  # The web front: automatic TLS for DOMAIN (ports 80 and 443 reachable from the",
        "  # internet), static and media files from the shared volume, the staff app, and",
        "  # everything else proxied to django. Its Caddyfile comes from the image through",
        "  # the release step, so after an update that changes it:",
        f"  #   docker compose -f {COMPOSE_FILE} exec caddy caddy reload --config {WEB_ROOT}/Caddyfile",
        "  caddy:",
        "    image: caddy:2-alpine",
        f'    command: ["caddy", "run", "--config", "{WEB_ROOT}/Caddyfile", "--adapter", "caddyfile"]',
        "    restart: unless-stopped",
        "    ports:",
        '      - "${KARNI_HTTP_PORT:-80}:80"',
        '      - "${KARNI_HTTPS_PORT:-443}:443"',
        '      - "${KARNI_HTTPS_PORT:-443}:443/udp"',
        "    environment:",
        *caddy_env,
        "    volumes:",
        f"      - app_data:{VOLUME}:ro",
        "      - caddy_data:/data",
        "      - caddy_config:/config",
        *_depends(options, django=True),
        "    healthcheck:",
        "      # Caddy's admin API answers inside the container only.",
        '      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:2019/config/"]',
        "      interval: 30s",
        "      timeout: 5s",
        "      retries: 3",
        "      start_period: 20s",
        "    logging: *logging",
        *_limits("KARNI_CADDY_MEMORY", "256M"),
        "",
    ]
    if options.db:
        out += [
            "  # PostgreSQL. Not published on the host: only the stack reaches it.",
            "  # POSTGRES_VERSION is a major version, and changing it on a volume that holds",
            "  # data needs an upgrade (dump and restore, docs/deploy.md).",
            "  db:",
            "    image: postgres:${POSTGRES_VERSION:-16}",
            "    restart: unless-stopped",
            "    environment:",
            "      POSTGRES_USER: ${POSTGRES_USER:-karni}",
            "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env.prod}",
            "      POSTGRES_DB: ${POSTGRES_DB:-karni}",
            "    volumes:",
            "      - postgres_data:/var/lib/postgresql/data",
            "    shm_size: 256mb",
            "    healthcheck:",
            '      test: ["CMD-SHELL", "pg_isready -U \\"$$POSTGRES_USER\\" -d \\"$$POSTGRES_DB\\""]',
            "      interval: 10s",
            "      timeout: 5s",
            "      retries: 10",
            "      start_period: 30s",
            "    logging: *logging",
            *_limits("KARNI_DB_MEMORY", "1G"),
            "",
        ]
    if options.redis:
        out += [
            "  # The Celery broker and the cache. Under memory pressure it evicts cache keys",
            "  # (they expire) and never a queued task.",
            "  redis:",
            "    image: redis:7-alpine",
            "    restart: unless-stopped",
            "    command:",
            '      ["redis-server", "--appendonly", "yes", "--maxmemory",',
            '       "${KARNI_REDIS_MAXMEMORY:-200mb}", "--maxmemory-policy", "volatile-lru"]',
            "    volumes:",
            "      - redis_data:/data",
            "    healthcheck:",
            '      test: ["CMD", "redis-cli", "ping"]',
            "      interval: 10s",
            "      timeout: 5s",
            "      retries: 10",
            "    logging: *logging",
            *_limits("KARNI_REDIS_MEMORY", "256M"),
            "",
        ]
    if options.backups:
        out += [
            "  # Database and media backups (karni-backup, docs/deploy.md#backups): one when",
            "  # due, every KARNI_BACKUP_INTERVAL_HOURS, the newest KARNI_BACKUP_KEEP kept in",
            "  # the backups volume and in KARNI_BACKUP_S3_BUCKET when it is set. Unhealthy",
            "  # while the last backup failed (E521). pg_dump is POSTGRES_VERSION's.",
            "  backup:",
            f"    image: ${{KARNI_IMAGE:-{slug}}}-backup:${{KARNI_TAG:-latest}}",
            "    build:",
            "      context: .",
            "      target: backup",
            "      args:",
            "        KARNI_SRC: ${KARNI_SRC:-}",
            "        POSTGRES_VERSION: ${POSTGRES_VERSION:-16}",
            f"    env_file: {ENV_FILE}",
            "    restart: unless-stopped",
            "    volumes:",
            "      # Read for each backup, written by a restore (docs/deploy.md#restore).",
            "      - app_data:/data",
            "      - backups:/backups",
            *_strip_redis(_depends(options)),
            "    healthcheck:",
            '      test: ["CMD", "karni-backup", "check"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 3",
            "      start_period: 30s",
            "    logging: *logging",
            *_limits("KARNI_BACKUP_MEMORY", "512M"),
            "",
        ]
    volumes = ["app_data", "caddy_data", "caddy_config"]
    if options.db:
        volumes.insert(0, "postgres_data")
    if options.redis:
        volumes.append("redis_data")
    if options.backups:
        volumes.append("backups")
    out += ["volumes:", *(f"  {name}:" for name in volumes)]
    return "\n".join(out) + "\n"


def _strip_redis(lines: list[str]) -> list[str]:
    """``depends_on`` lines without the redis entry (the backup never talks to Redis)."""
    out: list[str] = []
    skip = False
    for line in lines:
        if line == "      redis:":
            skip = True
            continue
        if skip and line.startswith("        condition:"):
            skip = False
            continue
        out.append(line)
    return [] if out == ["    depends_on:"] else out


_PROXY_SNIPPET = """\
# Django: gunicorn in the django service. While it restarts, caddy retries for up
# to 30 seconds instead of answering 502, so a quick update drops no request.
(django) {
	reverse_proxy django:8000 {
		lb_try_duration 30s
	}
}
"""

_FILES = """\
	# Static files (collectstatic) and uploads, straight from the shared volume.
	handle /static/* {
		root * {volume}
		import karni_headers
		file_server
	}
	handle /media/* {
		root * {volume}
		# Uploads are served as files and never run as a page's script.
		header X-Content-Type-Options "nosniff"
		header Content-Security-Policy "script-src 'none'"
		file_server
	}
"""


def _app_block(prefix: str, root: str, index: str) -> list[str]:
    assets = f"{prefix}assets/*"
    return [
        f"\t\troot * {root}",
        "\t\timport karni_headers",
        f"\t\t@assets path {assets}",
        '\t\theader @assets Cache-Control "public, max-age=31536000, immutable"',
        f"\t\t@pages not path {assets}",
        '\t\theader @pages Cache-Control "no-cache"',
        "\t\t# A route of the app (a reload, a link) answers with its index.html.",
        f"\t\ttry_files {{path}} {index}",
        "\t\tfile_server",
    ]


def caddyfile(options: Options) -> str:
    """The text of the ``Caddyfile``."""
    files = _FILES.replace("{volume}", VOLUME)
    out = [
        f"# The web front of {options.slug}'s production stack (docker-compose.prod.yml).",
        "# `karni make deploy compose` wrote it, and it is yours to edit. The release step",
        f"# publishes it with the image into {WEB_ROOT}/, next to the built staff app and",
        "# karni-headers.caddy: the security headers Django sends, from the project's",
        "# settings, for the files caddy serves itself.",
        "#",
        "# Caddy gets a TLS certificate for {$DOMAIN} by itself (Let's Encrypt or ZeroSSL)",
        "# once DNS points at the server and ports 80 and 443 reach it. A local name such",
        "# as localhost gets a certificate from Caddy's own local authority instead.",
        "{",
        "\t# Inside a container Caddy cannot add its local authority to a trust store.",
        "\tskip_install_trust",
        "\t# An address for the certificate authority's expiry notices:",
        "\t# email ops@example.com",
        "}",
        "",
        f"import {WEB_ROOT}/karni-headers.caddy",
        "",
        _PROXY_SNIPPET,
        "{$DOMAIN} {",
        "\tencode zstd gzip",
        "",
        files.rstrip("\n"),
    ]
    in_path = options.app and not options.app_domain and options.app_base != "/"
    at_root = options.app and not options.app_domain and options.app_base == "/"
    if in_path:
        prefix = options.app_base
        out += [
            "",
            f"\t# The staff app (frontend/), built into the image for {prefix}.",
            f"\tredir {prefix.rstrip('/')} {prefix} 308",
            f"\thandle {prefix}* {{",
            *_app_block(prefix, WEB_ROOT, f"{prefix}index.html"),
            "\t}",
            "",
            "\t# Everything else is Django: the API, the admin, /health/ and a public site.",
            "\thandle {",
            "\t\timport django",
            "\t}",
        ]
    elif at_root:
        out += [
            "",
            "\t# Django answers the API, /health/ and the admin (KARNI_ADMIN_PATH). Add any",
            "\t# other path Django serves here.",
            "\t@django path /api/* /health/* /healthz /readyz /{$KARNI_ADMIN_PATH}*",
            "\thandle @django {",
            "\t\timport django",
            "\t}",
            "",
            "\t# The staff app (frontend/) at the root of the site.",
            "\thandle {",
            *_app_block("/", f"{WEB_ROOT}/app", "/index.html"),
            "\t}",
        ]
    else:
        out += [
            "",
            "\t# Django: the API, the admin, /health/ and a public site.",
            "\thandle {",
            "\t\timport django",
            "\t}",
        ]
    out.append("}")
    if options.app_domain:
        out += [
            "",
            "# The staff app (frontend/) on its own host, with the API on the same origin.",
            "{$APP_DOMAIN} {",
            "\tencode zstd gzip",
            "",
            "\t@django path /api/* /health/* /healthz /readyz",
            "\thandle @django {",
            "\t\timport django",
            "\t}",
            "",
            "\thandle {",
            *_app_block("/", f"{WEB_ROOT}/app", "/index.html"),
            "\t}",
            "}",
        ]
    return "\n".join(out) + "\n"


def env_example(options: Options) -> str:
    """The text of ``.env.prod.example``."""
    hosts = [options.domain]
    origins = [f"https://{options.domain}"]
    if options.app_domain:
        hosts.append(options.app_domain)
        origins.append(f"https://{options.app_domain}")
    out = [
        f"# Production environment for {options.slug}. `karni make deploy compose` wrote it.",
        f"# Copy it to {ENV_FILE} on the server, fill in every empty value, and never commit",
        f"# {ENV_FILE}. docker-compose.prod.yml reads it, and every container runs",
        "# `karni check --deploy` first and refuses to start while a value is unsafe (E520).",
        f"#   cp {ENV_EXAMPLE} {ENV_FILE}",
        "",
        "# --- The site -------------------------------------------------------------------",
        "DJANGO_ENV=prod",
        f"PROJECT_NAME={options.slug}",
        "# The host Caddy gets a certificate for. Its DNS record points at this server.",
        f"DOMAIN={options.domain}",
    ]
    if options.app_domain:
        out += [
            "# The staff app's own host (a second DNS record).",
            f"APP_DOMAIN={options.app_domain}",
        ]
    out += [
        f"ALLOWED_HOSTS={','.join(hosts)}",
        f"CSRF_TRUSTED_ORIGINS={','.join(origins)}",
        "# 50 or more random characters, for example the output of:",
        '#   python3 -c "import secrets; print(secrets.token_urlsafe(50))"',
        "SECRET_KEY=",
        "# The admin's path, with a trailing slash, somewhere nobody guesses, for example:",
        "#   python3 -c \"import secrets; print('staff-' + secrets.token_hex(4) + '/')\"",
        "KARNI_ADMIN_PATH=",
        f"KARNI_AUTH_MODE={options.auth_mode}",
    ]
    if options.app:
        out += [
            "# The staff app's address: account emails link to it, and in session mode its",
            "# origin is trusted for CSRF.",
            f"KARNI_FRONTEND_URL={options.app_url}",
        ]
    out += [
        "# The country code a national phone number typed into a phone field gets: digits,",
        '# "44" for the UK (not "GB"), "1" for North America. Unset, only international',
        "# numbers (+44 ..., 0044 ...) are accepted.",
        "# KARNI_PHONE_COUNTRY_CODE=44",
        "# Copy here any other setting this project changed in .env (registration, roles,",
        "# KARNI_CSP for a font or analytics host, Sentry).",
        "",
        "# --- Email ----------------------------------------------------------------------",
        "# Password resets, account emails and the site's form notifications. The deploy",
        "# check refuses to start without a mail server and a sender of the site's domain",
        "# (karni.W520). A project that sends no email silences it in config/settings.py:",
        '#   SILENCED_SYSTEM_CHECKS += ["karni.W520"]',
        "# The mail server, host, port, user and password in one URL (smtps:// for SSL on",
        "# port 465). Write an @ in the user or password as %40.",
        "# EMAIL_URL=smtp+tls://user:password@smtp.example.com:587",
        "# The sender of every email, an address of the site's domain:",
        f"# DEFAULT_FROM_EMAIL=noreply@{options.domain}",
        "# The sender of the error reports Django mails to ADMINS:",
        f"# SERVER_EMAIL=server@{options.domain}",
        "",
        "# --- Database and Redis ---------------------------------------------------------",
    ]
    if options.db:
        out += [
            "# The db service's password, and the same password in DATABASE_URL. Letters and",
            '# digits need no escaping in the URL: python3 -c "import secrets; print(secrets.token_hex(24))"',
            "POSTGRES_PASSWORD=",
            "DATABASE_URL=postgres://karni:<POSTGRES_PASSWORD>@db:5432/karni",
            "# The database's major version: the db image and the backup's pg_dump.",
            "# POSTGRES_VERSION=16",
            "# The db service's user and database (the same names in DATABASE_URL):",
            "# POSTGRES_USER=karni",
            "# POSTGRES_DB=karni",
        ]
    else:
        out += [
            "# The managed database. Backups run pg_dump of POSTGRES_VERSION against it.",
            "DATABASE_URL=",
            "POSTGRES_VERSION=16",
        ]
    out.append("REDIS_URL=redis://redis:6379/0" if options.redis else "REDIS_URL=")
    if not options.celery:
        out += [
            "# No Celery worker runs, so /health/ready/ checks the database and the cache only.",
            "KARNI_HEALTH_CHECKS=karni.health.checks.check_database,karni.health.checks.check_cache",
        ]
    out += [
        "",
        "# --- Files ----------------------------------------------------------------------",
        "# Uploads and static files live in the app_data volume, which Caddy serves.",
        "KARNI_STORAGE=local",
        "MEDIA_ROOT=/data/media",
        "STATIC_ROOT=/data/static",
        "",
    ]
    if options.backups:
        out += [
            "# --- Backups (docs/deploy.md#backups) -------------------------------------------",
            "KARNI_BACKUP_KEEP=7",
            "KARNI_BACKUP_INTERVAL_HOURS=24",
            "# Also upload every backup to a bucket (any S3-compatible service):",
            "# KARNI_BACKUP_S3_BUCKET=",
            "# KARNI_BACKUP_S3_PREFIX=backups/",
            "# AWS_ACCESS_KEY_ID=",
            "# AWS_SECRET_ACCESS_KEY=",
            "# AWS_S3_ENDPOINT_URL=",
            "# AWS_S3_REGION_NAME=",
            "",
        ]
    out += [
        "# --- Sizing (defaults suit a server with 2 GB of memory) --------------------------",
        "# WEB_CONCURRENCY=2",
        "# KARNI_WORKER_CONCURRENCY=2",
        "# Memory limits per service:",
        "# KARNI_DJANGO_MEMORY=768M",
        "# KARNI_WORKER_MEMORY=768M",
        "# KARNI_BEAT_MEMORY=256M",
        "# KARNI_CADDY_MEMORY=256M",
        "# KARNI_DB_MEMORY=1G",
        "# KARNI_REDIS_MEMORY=256M",
        "# KARNI_REDIS_MAXMEMORY=200mb",
        "# KARNI_BACKUP_MEMORY=512M",
        "# Ports caddy publishes, when something else owns 80 and 443:",
        "# KARNI_HTTP_PORT=80",
        "# KARNI_HTTPS_PORT=443",
        "",
        "# --- The image --------------------------------------------------------------------",
        f"# Image name and tag: {options.slug}:latest by default. Tag each release (the git",
        "# commit) and set the previous tag here to roll back (docs/deploy.md#rollback).",
        f"# KARNI_IMAGE={options.slug}",
        "# KARNI_TAG=latest",
        "# A local Karni checkout instead of the releases (paths inside this project):",
        "# KARNI_SRC=.karni-src",
        "# KARNI_UI_TARBALL=.karni-ui/karni-ui.tgz",
        "",
        "# --- Emergency only ---------------------------------------------------------------",
        "# Starts the containers without `karni check --deploy`, logged on every start.",
        "# KARNI_SKIP_DEPLOY_CHECK=1",
    ]
    return "\n".join(out) + "\n"


# project facts


def _env_value(text: str | None, name: str) -> str | None:
    match = re.search(rf"^{name}=(.*)$", text or "", re.MULTILINE)
    return match.group(1).strip() if match else None


def project_slug(ws: Workspace) -> str:
    """``[project] name`` from pyproject.toml, else the directory name, as an image name."""
    name = ""
    text = ws.read("pyproject.toml")
    if text:
        try:
            name = str(tomllib.loads(text).get("project", {}).get("name", ""))
        except tomllib.TOMLDecodeError:
            name = ""
    name = re.sub(r"[^a-z0-9_.-]+", "_", (name or ws.root.name).lower()).strip("_.-")
    return name or "app"


def dockerfile_targets(text: str) -> set[str]:
    return {match.lower() for match in _TARGET.findall(text)}


def required_targets(options: Options) -> list[str]:
    needed = ["prod"]
    if options.app:
        needed.append("staff-app")
    if options.backups:
        needed.append("backup")
    return needed


def _ignore(ws: Workspace, filename: str, entry: str) -> None:
    text = ws.read(filename)
    if text is None:
        return
    if entry in {line.strip() for line in text.splitlines()}:
        return
    ws.write(filename, text + ("" if text.endswith("\n") or not text else "\n") + entry + "\n")


def plan(ws: Workspace, options: Options) -> None:
    """Plan the three files (and the two ignore entries) into ``ws``."""
    dockerfile = ws.read("Dockerfile")
    if dockerfile is None:
        raise CliError(
            "No Dockerfile in this project. The production stack builds its images from the "
            "Dockerfile's prod, staff-app and backup targets (a fresh `karni new` project has "
            "them, docs/deploy.md#an-existing-project shows them).",
            code="C105",
        )
    missing = [t for t in required_targets(options) if t not in dockerfile_targets(dockerfile)]
    if missing:
        raise CliError(
            f"The Dockerfile has no {', '.join(missing)} target"
            f"{'s' if len(missing) > 1 else ''}, which docker-compose.prod.yml builds. Add "
            f"{'them' if len(missing) > 1 else 'it'} from a fresh `karni new` project's "
            "Dockerfile (docs/deploy.md#an-existing-project), or leave out what needs "
            "it (--no-app for staff-app, --no-backups for backup).",
            code="C105",
        )
    ws.create(COMPOSE_FILE, compose(options))
    ws.create(CADDYFILE, caddyfile(options))
    ws.create(ENV_EXAMPLE, env_example(options))
    _ignore(ws, ".gitignore", ENV_FILE)
    _ignore(ws, ".dockerignore", ENV_FILE)
    if ws.read(".dockerignore") is None:
        ws.note(
            f"warning: no .dockerignore. Create one listing {ENV_FILE} and .env, or the "
            "image build copies their secrets into the image."
        )


def defaults(ws: Workspace, *, domain: str | None = None) -> Options:
    example = ws.read(".env.example")
    urls = ws.read("config/urls.py") or ""
    return Options(
        ready_path="/readyz" if "karni.health.probe_urls" in urls else "/health/",
        slug=project_slug(ws),
        domain=domain or _env_value(example, "DOMAIN") or DEFAULT_DOMAIN,
        auth_mode=_env_value(example, "KARNI_AUTH_MODE") or "jwt",
    )


def write_new_project(project: Path, *, domain: str, staff_app: bool = True) -> list[str]:
    """``karni new``'s step: the default stack, written quietly. Returns the written paths.

    ``staff_app=False`` (``karni new --no-staff-app``) serves no staff app, as ``--no-app``.
    """
    ws = Workspace(project)
    options = defaults(ws, domain=domain)
    plan(ws, options if staff_app else replace(options, app_path=None, app_domain=None))
    written = []
    for path, _before, after in ws.changes():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after, encoding="utf-8")
        written.append(ws.rel(path))
    return written


def _host(value: str, option: str) -> str:
    host = value.strip().lower()
    if not _HOST.match(host):
        raise CliError(
            f"{option} {value!r} is not a host name. Give the bare name, e.g. {option} "
            "example.com (no scheme, port or path).",
            code="C106",
        )
    return host


def command(
    target: str = typer.Argument(..., help="What to write. `compose`: the Docker Compose stack."),
    domain: str | None = typer.Option(
        None,
        "--domain",
        help="The site's host for .env.prod.example (default: DOMAIN in .env.example).",
    ),
    app_path: str = typer.Option(
        DEFAULT_APP_PATH,
        "--app-path",
        help="Path the staff app (frontend/) is served under, e.g. /app/ or /, on the site's host.",
    ),
    app_domain: str | None = typer.Option(
        None,
        "--app-domain",
        help="Serve the staff app on its own host instead, e.g. app.example.com.",
    ),
    app: bool = typer.Option(True, "--app/--no-app", help="Serve the staff app at all."),
    celery: bool = typer.Option(
        True, "--celery/--no-celery", help="Celery worker and beat services."
    ),
    backups: bool = typer.Option(True, "--backups/--no-backups", help="The backup service."),
    db: bool = typer.Option(
        True, "--db/--no-db", help="A PostgreSQL service (--no-db: a managed one)."
    ),
    redis: bool = typer.Option(
        True, "--redis/--no-redis", help="A Redis service (--no-redis: a managed one)."
    ),
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Write the production stack: docker-compose.prod.yml, the Caddyfile and .env.prod.example.

    One command then starts it on a server:
    `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`.
    Every file is the project's to edit. docs/deploy.md is the walk-through.
    """
    if target not in TARGETS:
        raise CliError(
            f"Unknown deploy target {target!r}. Known: {', '.join(TARGETS)} "
            "(karni make deploy compose).",
            code="C106",
        )
    if app_domain and app_path != DEFAULT_APP_PATH:
        raise CliError(
            "--app-path and --app-domain exclude each other: on its own host the staff app "
            "is served at /.",
            code="C106",
        )
    path = app_path.strip()
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    if not _APP_PATH.match(path):
        raise CliError(
            f"--app-path {app_path!r} is not a URL path. Use letters, digits, - and _ "
            "between slashes, e.g. /app/ or /staff/ or /.",
            code="C106",
        )
    if path in ("/static/", "/media/", "/api/", "/health/"):
        raise CliError(f"--app-path {path} is a path Django or Caddy already serves.", code="C106")
    ws = project_workspace(force or dry_run)  # a dry run shows the diff against what exists
    base = defaults(ws, domain=_host(domain, "--domain") if domain else None)
    options = Options(
        slug=base.slug,
        domain=base.domain,
        app_path=path if app else None,
        app_domain=_host(app_domain, "--app-domain") if app and app_domain else None,
        celery=celery,
        backups=backups,
        db=db,
        redis=redis,
        auth_mode=base.auth_mode,
        ready_path=base.ready_path,
    )
    plan(ws, options)
    if dry_run and not force:
        existing = [ws.rel(path) for path, before, _ in ws.changes() if before is not None]
        if existing:
            ws.note(
                f"{', '.join(existing)} exist{'s' if len(existing) == 1 else ''}: "
                "without --dry-run, pass --force to overwrite."
            )
    ws.note(
        f"next: cp {ENV_EXAMPLE} {ENV_FILE}, fill it in, then on the server: "
        f"docker compose -f {COMPOSE_FILE} --env-file {ENV_FILE} up -d --build "
        "(docs/deploy.md)"
    )
    ws.commit(dry_run=dry_run)
