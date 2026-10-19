"""``karni check`` — backend checks plus frontend duplicate detection.

Runs ``manage.py karni_check`` (system checks + ``karni.checks`` hooks,
including the architecture and duplication rules) and, when ``frontend/``
exists, jscpd via the project's own pinned binary driven solely by
``frontend/.jscpd.json``. Both steps always run; the exit code aggregates
both and each step's output is shown.

Outside CI, a clean run may end with one tip on stderr (:mod:`karni_cli.tips`,
at most once per project); ``-q`` suppresses it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import typer

from karni_cli import project as project_mod
from karni_cli import tips
from karni_cli.project import require_project

_BARE_IGNORE = re.compile(r"jscpd:ignore-start\s*$")


def _frontend_duplication(project: Path) -> int:
    frontend = project / "frontend"
    if not frontend.is_dir():
        return 0
    jscpd = frontend / "node_modules" / ".bin" / "jscpd"
    if not jscpd.exists():
        typer.echo(
            "karni check: jscpd not installed — run `npm install` in frontend/ "
            "(or pass --no-frontend to skip frontend duplication checks).",
            err=True,
        )
        return 1
    # Reason-required opt-outs: a bare jscpd:ignore-start (no reason after it)
    # is itself a failure; ignore-end legitimately carries nothing.
    bare = [
        f"{path.relative_to(project)}:{lineno}"
        for path in (frontend / "src").rglob("*.ts*")
        for lineno, line in enumerate(path.read_text().splitlines(), start=1)
        if _BARE_IGNORE.search(line)
    ]
    if bare:
        for location in bare:
            typer.echo(f"[duplicate] {location}: jscpd:ignore-start requires a reason", err=True)
        return 1
    proc = subprocess.run(
        [str(jscpd), "--config", ".jscpd.json"],
        cwd=frontend,
        text=True,
        check=False,
    )
    return proc.returncode


def _frontend_lint(project: Path) -> int:
    """``eslint .`` in frontend/ with the project's own binary (the @karni/ui rules live there)."""
    frontend = project / "frontend"
    if not frontend.is_dir():
        return 0
    eslint = frontend / "node_modules" / ".bin" / "eslint"
    if not eslint.exists():
        typer.echo(
            "karni check: eslint not installed — run `npm install` in frontend/ "
            "(or pass --no-frontend to skip the frontend checks).",
            err=True,
        )
        return 1
    proc = subprocess.run(
        [str(eslint), ".", "--max-warnings", "0"], cwd=frontend, text=True, check=False
    )
    return proc.returncode


def check(
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
    frontend: bool = typer.Option(True, "--frontend/--no-frontend"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Do not print the optional tip."),
) -> None:
    project = require_project()
    backend = project_mod.run_manage(
        project, ["karni_check"], docker=docker, service=service, capture=False
    ).returncode
    dup = _frontend_duplication(project) if frontend else 0
    lint = _frontend_lint(project) if frontend else 0
    if backend or dup or lint:
        sys.stderr.write("karni check: FAILED\n")
    else:
        # Only after a clean run (failures deserve the attention), never in CI,
        # and on stderr so stdout stays exactly the checks' output.
        tip = tips.history_tip(project, quiet=quiet)
        if tip:
            sys.stderr.write(f"\n{tip}\n")
    raise typer.Exit(1 if (backend or dup) else 0)
