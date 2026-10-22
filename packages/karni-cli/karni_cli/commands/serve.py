"""``karni serve`` — start the development stack.

Default: ``docker compose up`` in the project (the scaffold's compose file
runs django, worker, beat, db, redis and the frontend). ``--local`` instead
runs ``manage.py runserver`` through the project's ``.venv`` — no Docker.
"""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project


def serve(
    local: bool = typer.Option(
        False, "--local", help="Run manage.py runserver through the project .venv instead."
    ),
    host: str | None = typer.Option(None, "--host", help="--local only. Default 127.0.0.1."),
    port: int | None = typer.Option(None, "--port", help="--local only. Default 8000."),
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
