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
    """Fill every model with realistic demo data. It wraps `manage.py karni_seed [ARGS]`.

    Values come from field names and types (an `email` gets an email,
    `price` money, `starts_at` a near-future date). Relations point at
    seeded rows, and the same --seed gives the same rows. It prints a demo
    login (demo@example.com / karni-password). Per-model overrides live in
    `<app>/seeds.py` (`karni make seeder <Model>`).

    It first prints the models it will write to, and refuses when one of
    their tables already holds rows (users aside), because demo rows would
    mix with real content. Pass --reset to wipe the tables first or --force
    to add rows on top. Real content belongs in `karni load`.

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
