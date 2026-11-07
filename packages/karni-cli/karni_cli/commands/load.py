"""``karni load``: real content from a JSON or YAML file (``manage.py karni_load``)."""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli.project import require_project


def load(
    args: list[str] | None = typer.Argument(
        None,
        help="The content file, then options passed to manage.py karni_load: --dry-run, "
        "--refresh-files, --prune, --as USER, --json.",
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Load real content from a JSON or YAML file. It wraps `manage.py karni_load FILE [ARGS]`.

    The file maps model labels to lists of rows. Each row is matched by its
    natural key (`slug`, `email`, or `Karni.natural_key`) and created or
    updated, so the same file loads again without duplicates and says when
    nothing changed. Relations name their targets by natural key, file and
    image fields hold paths relative to the content file (uploaded once, or
    again with --refresh-files), and a nested list holds a row's children
    (--prune deletes the ones it does not name). One transaction with the
    API's validation: an invalid row rolls everything back. --dry-run lists,
    per model, each row it would create or change with the fields that change.
    `karni seed` is for demo data, `karni load` for real content (`karni design
    extract` writes it from a designer's pages).

    Example: karni load content/site.json --dry-run
    """
    project = require_project()
    proc = project_mod.run_manage(
        project,
        ["karni_load", *(args or [])],
        docker=docker,
        service=service,
        capture=False,
        database="connect",
    )
    raise typer.Exit(proc.returncode)
