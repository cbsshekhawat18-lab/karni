"""``karni make deploy systemd-nginx``: one Linux server without Docker, as files the project owns.

It writes a ``deploy/`` folder:

* ``deploy.sh``: the deploy, run on the server from the project's folder. Each run
  copies the project into a new release under ``<root>/releases/``, installs its
  dependencies into the release's own virtual environment, runs the deploy checks,
  the migrations and ``collectstatic``, points ``<root>/current`` at the release,
  installs and restarts the units, waits for ``/readyz`` on gunicorn's socket, then
  installs the nginx vhost and reloads nginx once ``nginx -t`` passes (and takes its
  own vhost out again when it does not). It keeps the newest releases
  (``--keep``), and ``--rollback`` switches back to an earlier one. It touches only
  its own paths and never writes over the ``.env`` on the server.
* ``web.service`` (gunicorn), and with Celery ``worker.service`` and ``beat.service``:
  systemd units, installed as ``<app>-web.service`` and so on.
* ``nginx.conf``: the vhost, TLS for the domain, ``/static/`` and ``/media/`` from
  disk, everything else proxied to gunicorn's socket.
* ``env.example``: every production value for this server. The first run copies it
  to ``<root>/shared/.env`` and stops, so the values are filled in on the server.
* ``README.md``: preparing the server, the first deploy, updates, rollback, logs.

The units and the vhost hold ``@APP@``, ``@ROOT@`` and the like, which ``deploy.sh``
fills in from the values at its top, so those values live in one place.

Override / escape hatch: every file is the project's to edit, ``--force`` writes them
again, and each value at the top of ``deploy.sh`` can be given for one run as
``DEPLOY_<NAME>`` in the environment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from karni_cli.generators.core import Workspace
from karni_cli.project import CliError

__all__ = ["FOLDER", "Options", "files", "plan"]

#: Where the files go in the project.
FOLDER = "deploy"
SCRIPT = f"{FOLDER}/deploy.sh"
DEFAULT_USER = "www-data"
DEFAULT_KEEP = 5
_TEMPLATES = Path(__file__).parent
_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_PATH = re.compile(r"^/[A-Za-z0-9._/-]*$")


@dataclass(frozen=True)
class Options:
    """What the server runs. Empty ``root``, ``cert`` and ``cert_key`` take their defaults."""

    slug: str
    domain: str
    root: str = ""
    user: str = DEFAULT_USER
    keep: int = DEFAULT_KEEP
    cert: str = ""
    cert_key: str = ""
    celery: bool = True
    auth_mode: str = "jwt"
    #: What deploy.sh asks gunicorn for before nginx sends it traffic.
    ready_path: str = "/readyz"
    #: A public site (karni_site): each release renders every page once (karni_site_seed).
    site: bool = False

    @property
    def app_root(self) -> str:
        return self.root or f"/srv/{self.slug}"

    @property
    def certificate(self) -> str:
        return self.cert or f"/etc/letsencrypt/live/{self.domain}/fullchain.pem"

    @property
    def certificate_key(self) -> str:
        return self.cert_key or f"/etc/letsencrypt/live/{self.domain}/privkey.pem"

    @property
    def units(self) -> list[str]:
        return ["web", "worker", "beat"] if self.celery else ["web"]


def validate(options: Options) -> Options:
    """``options`` when each value fits a path, a user name or a count, else ``C106``."""
    for flag, value in (
        ("--root", options.app_root),
        ("--cert", options.certificate),
        ("--cert-key", options.certificate_key),
    ):
        if value == "/" or not _PATH.match(value) or "//" in value or "/../" in f"{value}/":
            raise CliError(
                f"{flag} {value!r} is not an absolute path. Give one such as /srv/"
                f"{options.slug} (letters, digits, '.', '_', '-' and '/').",
                code="C106",
            )
    if not _USER.match(options.user):
        raise CliError(
            f"--user {options.user!r} is not a user name. Give the user the units run as, "
            f"such as {DEFAULT_USER}, the user nginx runs as on Debian and Ubuntu.",
            code="C106",
        )
    if options.keep < 2:
        raise CliError(
            f"--keep {options.keep}: keep 2 or more releases, so there is one to roll back to.",
            code="C106",
        )
    return options


def _fill(name: str, options: Options) -> str:
    text = (_TEMPLATES / name).read_text(encoding="utf-8")
    values = {
        "slug": options.slug,
        "domain": options.domain,
        "root": options.app_root,
        "user": options.user,
        "keep": str(options.keep),
        "cert": options.certificate,
        "cert_key": options.certificate_key,
        "units": " ".join(options.units),
        "ready_path": options.ready_path,
        "seed_step": (
            "  # Every page rendered once: the defaults its templates give are stored now,\n"
            "  # not on a visitor's request.\n"
            '  manage "$rel" karni_site_seed\n'
            if options.site
            else ""
        ),
    }
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def env_example(options: Options, email: list[str]) -> str:
    """The text of ``deploy/env.example``. ``email`` holds the sections shared with compose:
    the email, and the public site's for a project with karni-site."""
    root = options.app_root
    out = [
        f"# Production environment for {options.slug} on one server with systemd and nginx.",
        "# `karni make deploy systemd-nginx` wrote it. The first run of deploy/deploy.sh copies",
        f"# it to {root}/shared/.env and stops: fill in every empty value there, then run",
        "# deploy.sh again. deploy.sh never writes over that file. The units read it, and",
        "# `karni check --deploy` refuses to start while a value is unsafe.",
        "",
        "# --- The site -------------------------------------------------------------------",
        "DJANGO_ENV=prod",
        f"PROJECT_NAME={options.slug}",
        f"ALLOWED_HOSTS={options.domain}",
        f"CSRF_TRUSTED_ORIGINS=https://{options.domain}",
        "# 50 or more random characters, for example the output of:",
        '#   python3 -c "import secrets; print(secrets.token_urlsafe(50))"',
        "SECRET_KEY=",
        "# The admin's path, with a trailing slash, somewhere nobody guesses, for example:",
        "#   python3 -c \"import secrets; print('staff-' + secrets.token_hex(4) + '/')\"",
        "KARNI_ADMIN_PATH=",
        f"KARNI_AUTH_MODE={options.auth_mode}",
        "# The proxies in front of Django, for the client's address in rate limits: nginx.",
        "# Behind a CDN or a load balancer as well, 2.",
        "KARNI_NUM_PROXIES=1",
        "# Copy here any other setting this project changed in .env (registration, roles,",
        "# KARNI_CSP for a font or analytics host, Sentry).",
        "",
        *email,
        "",
        "# --- Database and Redis ---------------------------------------------------------",
        "# PostgreSQL on this server: the role and database deploy/README.md creates. Letters",
        '# and digits need no escaping in the URL: python3 -c "import secrets; print(secrets.token_hex(24))"',
        f"DATABASE_URL=postgres://{options.slug}:<password>@127.0.0.1:5432/{options.slug}",
        "# Redis on this server: the cache"
        + (" and the Celery broker." if options.celery else "."),
        "REDIS_URL=redis://127.0.0.1:6379/0",
    ]
    if not options.celery:
        out += [
            "# No Celery worker runs, so /health/ready/ checks the database and the cache only.",
            "KARNI_HEALTH_CHECKS=karni.health.checks.check_database,karni.health.checks.check_cache",
        ]
    out += [
        "",
        "# --- Files ----------------------------------------------------------------------",
        "# Uploads and collected static files, which nginx serves from disk.",
        "KARNI_STORAGE=local",
        f"MEDIA_ROOT={root}/shared/media",
        f"STATIC_ROOT={root}/shared/static",
        "",
        "# --- Sizing -----------------------------------------------------------------------",
        "# gunicorn worker processes, about two per CPU core:",
        "# WEB_CONCURRENCY=2",
    ]
    if options.celery:
        out.append("# KARNI_WORKER_CONCURRENCY=2")
    return "\n".join(out) + "\n"


def readme(options: Options) -> str:
    """The text of ``deploy/README.md``."""
    slug, root, domain = options.slug, options.app_root, options.domain
    units = ", ".join(f"`{slug}-{unit}`" for unit in options.units)
    packages = (
        "python3 python3-venv nginx postgresql redis-server curl certbot python3-certbot-nginx"
    )
    unit_rows = [f"| `web.service` | gunicorn, the web process, as `{slug}-web.service`. |"]
    if options.celery:
        unit_rows += [
            f"| `worker.service` | the Celery worker, as `{slug}-worker.service`. |",
            f"| `beat.service` | Celery beat, as `{slug}-beat.service`. Run exactly one. |",
        ]
    return "\n".join(
        [
            f"# Deploying {slug} with systemd and nginx",
            "",
            "`karni make deploy systemd-nginx` wrote this folder, and every file in it is",
            "yours to edit. It runs the project on one Linux server without Docker: the",
            f"processes under systemd ({units}), nginx in front with TLS, and PostgreSQL",
            "and Redis on the same server. Karni's docs/deploy.md has the whole walk-through.",
            "",
            "| File | What it is |",
            "|---|---|",
            "| `deploy.sh` | The deploy, run on the server: a new release, its checks and migrations, the switch, the units, nginx. `--rollback` and `--list` too. |",
            *unit_rows,
            f"| `nginx.conf` | The vhost, as `/etc/nginx/sites-available/{slug}.conf`. |",
            f"| `env.example` | Every production value. The first deploy copies it to `{root}/shared/.env`. |",
            "",
            "The units and the vhost hold `@APP@`, `@ROOT@` and the like. `deploy.sh` fills",
            "them in from the values at its top (the app's name, the domain, the folder, the",
            "user the units run as, the releases kept, the certificate), so change a value",
            "there. `DEPLOY_<NAME>` in the environment replaces one for a single run.",
            "",
            "## What deploy.sh touches",
            "",
            f"- `{root}/`: `releases/<id>/` (one folder per deploy), `current` (a link to the",
            "  running release), `shared/.env`, `shared/media/` (uploads) and `shared/static/`",
            "  (collectstatic).",
            f"- `/etc/systemd/system/{slug}-*.service`.",
            f"- `/etc/nginx/sites-available/{slug}.conf` and its link in `sites-enabled/`.",
            "",
            "Nothing else: other sites on the server, their vhosts and their units stay as",
            "they are. `nginx -t` runs before every reload. When it fails, deploy.sh puts the",
            "previous vhost back, or removes its link when there was none, and stops without",
            "reloading nginx. It writes `shared/.env` once and never writes over it.",
            "",
            "## Prepare the server, once",
            "",
            "```sh",
            f"sudo apt install {packages}",
            f"sudo -u postgres createuser --pwprompt {slug}     # the password goes in DATABASE_URL",
            f"sudo -u postgres createdb --owner {slug} {slug}",
            f"sudo certbot certonly --nginx -d {domain}        # or set CERT and CERT_KEY in deploy.sh",
            "```",
            "",
            f"The units run as `{options.user}`. With `www-data`, the user nginx runs as on",
            "Debian and Ubuntu, nginx can open gunicorn's socket.",
            "",
            "## The first deploy",
            "",
            "Put the project on the server, for example with git, then run the script:",
            "",
            "```sh",
            f"git clone https://git.example.com/you/{slug}.git && cd {slug}",
            f"sudo deploy/deploy.sh                     # writes {root}/shared/.env and stops",
            f"sudo editor {root}/shared/.env            # fill in every empty value",
            "sudo deploy/deploy.sh                     # the release, the units, nginx",
            "```",
            "",
            "## Updates",
            "",
            "```sh",
            "git pull && sudo deploy/deploy.sh",
            "```",
            "",
            "Each run is a new release. When the web process does not answer",
            f"`{options.ready_path}` with 200 on its socket, the run stops before nginx, and",
            "says which release `--rollback` goes back to.",
            "",
            "## Rollback",
            "",
            "```sh",
            "deploy/deploy.sh --list                   # the releases, the current one marked",
            "sudo deploy/deploy.sh --rollback          # the release before the current one",
            "sudo deploy/deploy.sh --rollback <id>     # a release --list shows",
            "```",
            "",
            "A rollback runs no migration. When the earlier code cannot run with the newer",
            "migrations, reverse them first, with the newer release's code:",
            f"`cd {root}/current && sudo -u {options.user} .venv/bin/python manage.py migrate <app> <migration>`.",
            "",
            "## Logs",
            "",
            "```sh",
            f"journalctl -u {slug}-web -f",
            f"tail -f /var/log/nginx/{slug}.error.log",
            "```",
            "",
        ]
    )


def files(options: Options, email: list[str]) -> dict[str, str]:
    """Every file of ``deploy/`` by its path in the project."""
    found = {
        SCRIPT: _fill("deploy.sh", options),
        **{f"{FOLDER}/{unit}.service": _fill(f"{unit}.service", options) for unit in options.units},
        f"{FOLDER}/nginx.conf": _fill("nginx.conf", options),
        f"{FOLDER}/env.example": env_example(options, email),
        f"{FOLDER}/README.md": readme(options),
    }
    return found


def plan(ws: Workspace, options: Options, email: list[str]) -> None:
    """Plan the ``deploy/`` folder into ``ws``."""
    for path, text in files(validate(options), email).items():
        ws.create(path, text)


def make_executable(ws: Workspace) -> None:
    """``chmod +x deploy/deploy.sh`` once it is written."""
    script = ws.path(SCRIPT)
    if script.is_file():
        script.chmod(script.stat().st_mode | 0o111)
