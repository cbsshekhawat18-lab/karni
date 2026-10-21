"""``karni seed`` — realistic, deterministic demo data (``manage.py karni_seed``)."""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def seed(
    args: list[str] | None = typer.Argument(
        None,
        help="Passed to manage.py karni_seed: --count N, --seed S, --reset, --model app.Model, "
        "--json, --force.",
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Fill every model with realistic demo data — wraps `manage.py karni_seed [ARGS]`.

    Values come from field names and types (an `email` gets an email,
    `price` money, `starts_at` a near-future date); relations point at
    seeded rows; the same --seed gives the same rows. Prints a demo login
    (demo@example.com / karni-password). Per-model overrides live in
    <app>/seeds.py (`karni make seeder <Model>`).

    Example: karni seed --count 20 --seed 42 --reset
    """
    project = require_project()
    proc = project_mod.run_manage(
        project,
        ["karni_seed", *(args or [])],
        docker=docker,
        service=service,
        capture=False,
        database="connect",
    )
    raise typer.Exit(proc.returncode)
