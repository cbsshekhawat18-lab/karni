"""``karni serve`` — start the development stack.

Default: ``docker compose up`` in the project (the scaffold's compose file
runs django, worker, beat, db, redis and the frontend). ``--local`` instead
runs ``manage.py runserver`` through the project's ``.venv`` — no Docker.

One setting picks the dev port: ``KARNI_DEV_PORT`` in the environment or the
project's ``.env`` (default 8000). ``--local`` runs Django on it, and the
scaffold's ``frontend/vite.config.ts`` proxies ``/api`` and ``/health`` to
``127.0.0.1`` on the same port. ``KARNI_API_PROXY`` points the frontend's
dev server elsewhere (docker compose sets it for its container). When the
server and that proxy disagree (``--port``, ``--host``, or a frontend
config older than ``KARNI_DEV_PORT``), ``--local`` prints how to point the
frontend at the server.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from karni_cli import envfile
from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project

#: The dev port when ``KARNI_DEV_PORT`` is unset.
DEFAULT_PORT = 8000
#: Where a frontend config without ``KARNI_DEV_PORT`` proxies when ``KARNI_API_PROXY`` is unset.
DEFAULT_API_PROXY = f"http://127.0.0.1:{DEFAULT_PORT}"
#: The setting naming the dev port, read by ``serve --local`` and the scaffold's vite.config.ts.
DEV_PORT = "KARNI_DEV_PORT"
#: Bind-all addresses: the browser-side proxy still reaches them on loopback.
_ANY_HOST = frozenset({"0.0.0.0", "::", "[::]"})


def api_proxy_target(host: str, port: int) -> str:
    """The ``KARNI_API_PROXY`` value that reaches ``runserver host:port`` from the dev server."""
    reachable = "127.0.0.1" if host in _ANY_HOST else host
    return f"http://{reachable}:{port}"


def dev_port(project: Path) -> int:
    """``KARNI_DEV_PORT`` from the environment or the project's ``.env``, else 8000.

    :raises CliError: C007 when the value is not a port number.
    """
    found = envfile.lookup(project, DEV_PORT)
    if found is None or not found.text.strip():
        return DEFAULT_PORT
    text = found.text.strip()
    if text.isdigit() and 0 < int(text) < 65536:
        return int(text)
    raise CliError(
        f"{DEV_PORT}={found.text!r} (from {found.origin}) is not a port number. Set it to a "
        f"port between 1 and 65535 (for example {DEV_PORT}=8020), or remove it to use "
        f"{DEFAULT_PORT}.",
        code="C007",
    )


def _reads_dev_port(config: Path) -> bool:
    """Whether the frontend's vite.config.ts is the shape that reads ``KARNI_DEV_PORT`` and .env."""
    try:
        return DEV_PORT in config.read_text(encoding="utf-8")
    except OSError:
        return False


def frontend_proxy_target(project: Path) -> str | None:
    """Where the frontend's dev server proxies ``/api``, or ``None`` without a Vite frontend.

    The scaffold's config takes ``KARNI_API_PROXY``, else ``127.0.0.1`` at
    ``KARNI_DEV_PORT``, both from the environment or ``.env``. An older config
    reads only ``KARNI_API_PROXY`` from the environment and defaults to 8000.
    """
    config = project / "frontend" / "vite.config.ts"
    if not config.is_file():
        return None
    if not _reads_dev_port(config):
        return os.environ.get("KARNI_API_PROXY") or DEFAULT_API_PROXY
    proxy = envfile.lookup(project, "KARNI_API_PROXY")
    if proxy is not None and proxy.text:
        return proxy.text
    return api_proxy_target("127.0.0.1", dev_port(project))


def proxy_hint(project: Path, host: str, port: int) -> str | None:
    """How to point the frontend's dev server at this runserver, or ``None`` when it already is.

    ``None`` too when the project has no Vite frontend.
    """
    target = api_proxy_target(host, port)
    frontend = frontend_proxy_target(project)
    if frontend is None or frontend == target:
        return None
    # KARNI_DEV_PORT moves both for good, when the dev server derives its
    # target from it and the server listens on loopback.
    port_fixes_it = (
        _reads_dev_port(project / "frontend" / "vite.config.ts")
        and envfile.lookup(project, "KARNI_API_PROXY") is None
        and api_proxy_target("127.0.0.1", port) == target
    )
    start = "Start the dev server with:"
    if port_fixes_it:
        start = (
            f"Set {DEV_PORT}={port} in .env: karni serve --local and the dev server both read "
            f"it. Or start the dev server with:"
        )
    return (
        f"frontend: the dev server proxies /api to {frontend}, not to {target}. {start}\n"
        f"  cd frontend && KARNI_API_PROXY={target} npm run dev"
    )


def serve(
    local: bool = typer.Option(
        False, "--local", help="Run manage.py runserver through the project .venv instead."
    ),
    host: str | None = typer.Option(None, "--host", help="--local only. Default 127.0.0.1."),
    port: int | None = typer.Option(
        None,
        "--port",
        help="--local only. Default: KARNI_DEV_PORT from the environment or .env, else 8000 "
        "(the frontend's dev server proxies to the same port). Another port prints how to "
        "point the frontend at it.",
    ),
    build: bool = typer.Option(False, "--build", help="compose only: rebuild images first."),
    detach: bool = typer.Option(False, "--detach", "-d", help="compose only: run in background."),
) -> None:
    """Start the dev stack. It wraps `docker compose up` (or `manage.py runserver` with --local)."""
    project = require_project()
    if local:
        if build or detach:
            raise CliError(
                "--build/--detach apply to docker compose. Drop them or drop --local.", code="C004"
            )
        if project_mod.venv_python(project) is None:
            raise CliError(
                "karni serve --local needs the project's .venv "
                "(uv venv && uv pip install -r pyproject.toml).\n"
                "Without one, drop --local to run the docker compose stack.",
                code="C002",
            )
        port = port if port is not None else dev_port(project)
        addrport = f"{host or '127.0.0.1'}:{port}"
        hint = proxy_hint(project, host or "127.0.0.1", port)
        if hint is not None:
            typer.echo(hint)
        # runserver checks for unapplied migrations on start, so it opens the database.
        proc = project_mod.run_manage(
            project, ["runserver", addrport], docker=False, capture=False, database="connect"
        )
    else:
        if host is not None or port is not None:
            raise CliError(
                "--host/--port need --local. Under docker compose, docker-compose.yml "
                f"publishes Django on {DEV_PORT} from .env (default {DEFAULT_PORT}).",
                code="C004",
            )
        args = ["up", *(["--build"] if build else []), *(["--detach"] if detach else [])]
        proc = project_mod.run_compose(project, args)
    raise typer.Exit(proc.returncode)
