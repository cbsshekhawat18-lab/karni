"""``karni test`` — the project's test suite (pytest) through the project interpreter."""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def test(
    args: list[str] | None = typer.Argument(
        None, help="Passed to pytest: paths, -k EXPR, -x, --lf … (use -- before --help)."
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Run the test suite — wraps `python -m pytest [ARGS]`."""
    project = require_project()
    proc = project_mod.run_python(
        project,
        ["-m", "pytest", *(args or [])],
        docker=docker,
        service=service,
        capture=False,
        interactive=True,
    )
    raise typer.Exit(proc.returncode)
