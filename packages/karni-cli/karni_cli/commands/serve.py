"""``karni serve`` — start the development stack.

Default: ``docker compose up`` in the project (the scaffold's compose file
runs django, worker, beat, db, redis and the frontend). ``--local`` instead
runs ``manage.py runserver`` through the project's ``.venv`` — no Docker.

The frontend's Vite dev server proxies ``/api`` and ``/health`` to
``127.0.0.1:8000`` unless ``KARNI_API_PROXY`` says otherwise. ``--local`` on
another address prints the exact ``KARNI_API_PROXY=... npm run dev`` line, so
``--port`` is the only thing to choose.
"""

from __future__ import annotations

from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project

#: Where the scaffold's ``vite.config.ts`` proxies when ``KARNI_API_PROXY`` is unset.
DEFAULT_API_PROXY = "http://127.0.0.1:8000"
#: Bind-all addresses: the browser-side proxy still reaches them on loopback.
_ANY_HOST = frozenset({"0.0.0.0", "::", "[::]"})


def api_proxy_target(host: str, port: int) -> str:
    """The ``KARNI_API_PROXY`` value that reaches ``runserver host:port`` from the dev server."""
    reachable = "127.0.0.1" if host in _ANY_HOST else host
    return f"http://{reachable}:{port}"


def proxy_hint(project: Path, host: str, port: int) -> str | None:
    """The line that points the frontend's dev server at this runserver, or ``None``.

    ``None`` when the project has no Vite frontend or the default proxy
    target already reaches the server.
    """
    target = api_proxy_target(host, port)
    if target == DEFAULT_API_PROXY or not (project / "frontend" / "vite.config.ts").is_file():
        return None
    return (
        f"frontend: the dev server proxies to {DEFAULT_API_PROXY} by default. Start it with:\n"
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
        help="--local only. Default 8000. Another port prints the KARNI_API_PROXY line "
        "that points the frontend's dev server at it.",
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
        addrport = f"{host or '127.0.0.1'}:{port or 8000}"
        hint = proxy_hint(project, host or "127.0.0.1", port or 8000)
        if hint is not None:
            typer.echo(hint)
        # runserver checks for unapplied migrations on start, so it opens the database.
        proc = project_mod.run_manage(
            project, ["runserver", addrport], docker=False, capture=False, database="connect"
        )
    else:
        if host is not None or port is not None:
            raise CliError(
                "--host/--port need --local. Under docker compose the port is set in "
                "docker-compose.yml (8000).",
                code="C004",
            )
        args = ["up", *(["--build"] if build else []), *(["--detach"] if detach else [])]
        proc = project_mod.run_compose(project, args)
    raise typer.Exit(proc.returncode)
