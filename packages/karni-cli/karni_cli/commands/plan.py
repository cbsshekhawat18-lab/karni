"""``karni plan`` (experimental): what ``karni build`` would change, writing nothing.

    karni plan                       karni.yaml against this project
    karni plan --spec other.yaml --json
    karni plan --offline             no row counts: the database is not opened

See :mod:`karni_cli.spec.plan` and docs/app-spec.md. The spec modules (and
Pydantic) are imported inside the command, so ``karni --help`` stays fast.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli.commands.spec import _default_spec
from karni_cli.project import CliError


def plan(
    spec: Path | None = typer.Option(
        None,
        "--spec",
        help="The spec file. Default: karni.yaml in the project root, else in this directory.",
        show_default=False,
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print {version, file, valid, issues, changes: [{area, action, target, detail, "
        "risky, reason, rows}], summary, row_counts} (docs/assets/karni-plan.schema.json).",
    ),
    offline: bool = typer.Option(
        False, "--offline", help="Do not open the database: risky changes show no row counts."
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Experimental. Compare karni.yaml with the project and print what karni build would change.

    It validates the spec (karni spec validate's codes), reads the project the
    way karni spec export does (manage.py karni_facts), compares both in one
    normal form and prints one line per change, grouped by area: + add,
    ~ change or rename, - remove, ! risky. A risky change can lose data or open
    it to more people (a field or entity removed, a type changed, a relation
    pointed elsewhere, a module removed, a key type switched, access widened),
    with the rows it affects when the database answers (manage.py karni_rows,
    only SELECT COUNT). karni build refuses risky changes without
    --allow-destructive. It writes nothing. Exit status 1 when the spec has a
    problem.
    """
    from karni_cli.spec import plan as plan_mod
    from karni_cli.spec.export import read_facts
    from karni_cli.spec.validate import validate_text

    root = project_mod.require_project()
    path = spec or _default_spec()
    if not path.is_file():
        raise CliError(
            f"No spec at {path}. Write one (docs/app-spec.md), export the project's with "
            "karni spec export -o karni.yaml, or pass --spec <file>.",
            code="C210",
        )
    shown = path.name if spec is None else str(spec)
    text = path.read_text(encoding="utf-8")
    report = validate_text(text)
    facts = None
    if report.ok:
        facts = read_facts(root, docker=docker, service=service, command="karni plan", code="C250")
        report = validate_text(text, databases=facts.get("databases"))
    if not report.ok or report.spec is None or facts is None:
        if as_json:
            issues = [issue.as_dict() for issue in report.issues]
            typer.echo(json.dumps(plan_mod.invalid_output(shown, issues), indent=2))
        else:
            for issue in report.issues:
                typer.echo(issue.render(shown))
            count = len(report.issues)
            typer.echo(f"{shown}: {count} problem{'s' if count != 1 else ''}, so no plan.")
        raise typer.Exit(1)
    result = plan_mod.plan_project(report.spec, facts, root, file=shown)
    counter = None if offline else plan_mod.manage_counter(root, docker=docker, service=service)
    plan_mod.apply_counts(result, counter)
    if as_json:
        typer.echo(json.dumps(plan_mod.checked_output(result.as_dict()), indent=2))
    else:
        typer.echo(result.text(), nl=False)
