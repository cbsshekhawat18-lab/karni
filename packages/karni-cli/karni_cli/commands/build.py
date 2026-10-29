"""``karni build`` (experimental): apply ``karni plan`` to the project, idempotently.

    karni build                         karni.yaml in the project root
    karni build --dry-run               the plan and the files it would write
    karni build --allow-destructive     apply risky changes too (each is named first)
    karni build --force                 replace Karni-owned files edited by hand (.orig kept)
    karni build --adopt <file>          hand a Karni-owned file to the project
    karni build --json

See :mod:`karni_cli.builder` and docs/app-spec.md. The build modules (and
Pydantic) are imported inside the command, so ``karni --help`` stays fast.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli.commands.spec import _default_spec
from karni_cli.project import CliError


def build(
    spec: Path | None = typer.Option(
        None,
        "--spec",
        help="The spec file. Default: karni.yaml in the project root, else in this directory.",
        show_default=False,
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the plan and the files it would write. Write nothing."
    ),
    allow_destructive: bool = typer.Option(
        False,
        "--allow-destructive",
        help="Apply the risky (!) changes too: a field or entity removed, a type narrowed, "
        "access widened. Without it they stop the build (C270), each named with its rows.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace Karni-owned files edited by hand, keeping each as <file>.orig.",
    ),
    adopt: list[str] | None = typer.Option(
        None,
        "--adopt",
        help="Hand a Karni-owned file (or config/settings.py, frontend/src/routes.tsx for "
        "their blocks) to the project: karni build stops managing it. Repeatable.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print {version, file, valid, issues, status, code, message, plan, files, "
        "hand_edits, adopted, steps, next} (docs/assets/karni-build.schema.json).",
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Experimental. Make the project match karni.yaml, without touching hand-written code.

    It computes karni plan, refuses risky changes without --allow-destructive
    (C270), checks that no Karni-owned file was edited by hand (C273), then
    runs in order: karni add for each new module, the Karni-owned files
    (<app>/karni/models.py, api.py, seeds.py, <app>/tests/karni/,
    frontend/src/pages/karni/, the karni:spec blocks of config/settings.py
    and routes.tsx) and the project's own files once (<app>/models.py,
    viewsets.py, seeds.py: a subclass per entity, never overwritten),
    makemigrations then migrate, seed (only tables it created, only while
    empty), karni types, karni test, then karni check. It stops at the first
    failure with its code and what to do next, and the next karni build
    continues from there. Run twice with no change, it writes nothing.
    Fingerprints live in .karni/build.json (commit it). Exit status 1 when
    it stops.
    """
    from karni_cli.builder.run import Options, Result
    from karni_cli.builder.run import build as run_build
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
        facts = read_facts(root, docker=docker, service=service, command="karni build", code="C250")
        report = validate_text(text, databases=facts.get("databases"))
    if not report.ok or report.spec is None or facts is None:
        result = Result(shown, status="invalid", issues=[i.as_dict() for i in report.issues])
        if as_json:
            typer.echo(json.dumps(result.as_dict(), indent=2))
        else:
            for issue in report.issues:
                typer.echo(issue.render(shown))
            count = len(report.issues)
            typer.echo(f"{shown}: {count} problem{'s' if count != 1 else ''}, so no build.")
        raise typer.Exit(1)
    opts = Options(
        dry_run=dry_run,
        allow_destructive=allow_destructive,
        force=force,
        adopt=tuple(adopt or ()),
        docker=docker,
        service=service,
    )
    result = run_build(root, report.spec, facts, shown, opts)
    if as_json:
        typer.echo(json.dumps(result.as_dict(), indent=2))
    else:
        typer.echo(result.text(), nl=False)
    if not result.ok:
        raise typer.Exit(1)
