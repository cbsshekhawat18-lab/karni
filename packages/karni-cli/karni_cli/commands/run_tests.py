"""``karni test`` — the project's test suite (pytest) through the project interpreter."""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project


def test(
    args: list[str] | None = typer.Argument(
        None, help="Passed to pytest: paths, -k EXPR, -x, --lf … (use -- before --help)."
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Run the test suite. It wraps `python -m pytest [ARGS]`."""
    project = require_project()
    probe = project_mod.run_python(
        project, ["-c", "import pytest"], docker=docker, service=service, capture=True
    )
    if probe.returncode != 0 and "No module named" in (probe.stderr or ""):
        raise CliError(
            "pytest is not installed in the project interpreter, so `karni test` cannot run.\n"
            "Install the project's dev group there: pip install pytest pytest-django "
            "(or `uv sync`), then run karni test again.",
            code="C011",
        )
    proc = project_mod.run_python(
        project,
        ["-m", "pytest", *(args or [])],
        docker=docker,
        service=service,
        capture=False,
        interactive=True,
        database="connect",  # pytest-django creates the test database on that server
    )
    raise typer.Exit(proc.returncode)
