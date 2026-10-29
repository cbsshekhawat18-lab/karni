"""``karni spec`` (experimental): the app spec, ``karni.yaml``.

    karni spec validate                  check ./karni.yaml (or the project's)
    karni spec validate --spec other.yaml --json
    karni spec export                    print the project's spec
    karni spec export -o karni.yaml      write it (--force replaces a file)

See :mod:`karni_cli.spec` and docs/app-spec.md. The spec modules (and
Pydantic) are imported inside the commands, so ``karni --help`` stays fast.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError

spec_app = typer.Typer(
    help=(
        "The app spec, karni.yaml (experimental): check it (validate) or write it from an "
        "existing project (export)."
    ),
    no_args_is_help=True,
    add_completion=False,
)

SPEC_FILE = "karni.yaml"


def _default_spec() -> Path:
    root = project_mod.find_project()
    return (root or Path.cwd()) / SPEC_FILE


@spec_app.command("validate")
def validate(
    spec: Path | None = typer.Option(
        None,
        "--spec",
        help="The spec file. Default: karni.yaml in the project root, else in this directory.",
        show_default=False,
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Print {file, valid, issues: [{code, line, path, message, fix}]}."
    ),
) -> None:
    """Experimental. Check a karni.yaml: every problem with its code, line and fix.

    It checks the YAML, every key and value (unknown keys are errors, keys that
    start with x- are kept and ignored), each field through karni make model's
    own parser, and every reference: relations, roles named in access, grants,
    pages, modules, field groups, keys and owners. Codes are C211 to C242
    (karni explain <code>). Exit status 1 when there is a problem.
    """
    from karni_cli.spec.validate import validate_text

    path = spec or _default_spec()
    if not path.is_file():
        raise CliError(
            f"No spec at {path}. Write one (docs/app-spec.md), export the project's with "
            "karni spec export -o karni.yaml, or pass --spec <file>.",
            code="C210",
        )
    report = validate_text(path.read_text(encoding="utf-8"))
    shown = path.name if spec is None else str(spec)
    if as_json:
        payload = {
            "file": shown,
            "valid": report.ok,
            "issues": [issue.as_dict() for issue in report.issues],
        }
        typer.echo(json.dumps(payload, indent=2))
    else:
        for issue in report.issues:
            typer.echo(issue.render(shown))
        if report.ok and report.spec is not None:
            entities = sum(len(app.entities) for app in report.spec.apps.values())
            typer.echo(
                f"{shown}: valid ({len(report.spec.apps)} app(s), {entities} entities, "
                f"{len(report.spec.roles)} role(s), {len(report.spec.pages)} page entries)."
            )
        else:
            count = len(report.issues)
            typer.echo(f"{shown}: {count} problem{'s' if count != 1 else ''}.")
    if not report.ok:
        raise typer.Exit(1)


@spec_app.command("export")
def export(
    output: Path | None = typer.Option(
        None, "-o", "--output", help="Write the spec to this file. Default: print it."
    ),
    force: bool = typer.Option(False, "--force", help="Replace the output file if it exists."),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Experimental. Write the spec of this project from its code (manage.py karni_facts).

    The models become entities (each field in the field syntax when its type
    makes the same column), the viewsets their access and search, KARNI_ROLES
    the roles, the settings the features, the installed modules and their
    changed settings the modules, frontend/src/routes.tsx the pages, and the
    seeders the seed counts. What the spec cannot express is listed, and kept
    as comments at the top of the file. The file starts with a
    yaml-language-server line naming the JSON Schema, for editors.
    """
    from karni_cli.spec.export import export_project

    root = project_mod.require_project()
    if output is not None and output.exists() and not force:
        raise CliError(
            f"{output} exists, and karni spec export does not overwrite it: it may hold your "
            "own edits. Pass --force to replace it, or -o another file.",
            code="C246",
        )
    exported = export_project(root, docker=docker, service=service)
    text = exported.text()
    if output is None:
        typer.echo(text, nl=False)
        for line in exported.left_out:
            typer.echo(f"not in the spec: {line}", err=True)
        return
    output.write_text(text, encoding="utf-8")
    typer.echo(f"{output}: written")
    for line in exported.left_out:
        typer.echo(f"not in the spec: {line}")
    typer.echo(f"next: karni spec validate --spec {output}")
