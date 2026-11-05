"""``karni suggest`` (experimental): what Karni could do that the project does by hand.

    karni suggest             the suggestions, with the file, line and fix of each
    karni suggest --json      {version, enabled, suggestions: [...]}
                              (docs/assets/karni-suggestions.schema.json)

The same block ends ``karni check`` and ``karni doctor``. A suggestion never
fails a run: this command exits 0 whatever it finds. See
:mod:`karni_cli.suggest` and docs/enforcement.md#suggestions.
"""

from __future__ import annotations

import json

import typer

from karni_cli import suggest as suggest_mod
from karni_cli.project import CliError, require_project


def suggest(
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print {version, enabled, suggestions: [{code, rule, file, line, message, fix, "
        "command}]} (docs/assets/karni-suggestions.schema.json).",
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Experimental. Print what Karni could do that the project does by hand.

    Each suggestion has a stable code (SUG001 to SUG007, karni explain SUG001),
    names the file and line, and gives the exact command or change: a tree
    model, a MarkdownField, the aggregate declaration, a taxonomy, a module to
    remove or add, a karni.yaml that drifted from the code. Silence one with
    `# karni: allow(<rule>): <reason>` on its line, or all of them with
    KARNI_SUGGESTIONS = False in config/settings.py. Exit status 0 always.

    Example: karni suggest --json
    """
    project = require_project()
    core = None
    try:
        core = suggest_mod.core_suggestions(project, docker=docker, service=service)
    except CliError as exc:
        typer.echo(f"error: {exc}", err=True)
    data = suggest_mod.collect(project, core, docker=docker, service=service)
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    if not data["enabled"]:
        typer.echo("suggestions: off (KARNI_SUGGESTIONS = False)")
    elif not data["suggestions"]:
        typer.echo("suggestions: none")
    else:
        typer.echo(suggest_mod.render(data))
