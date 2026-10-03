"""``karni upgrade`` — move a project across Karni versions.

1. Find where the project is: the karni its interpreter has installed
   (``--from`` overrides), and where it goes: ``--to``, default the newest
   release in the changelog this karni-cli carries.
2. Select every recorded breaking change in between, in release order
   (:func:`karni_cli.upgrades.changelog.select`).
3. Run their codemods over a scratch copy; ``--dry-run`` prints the diff,
   otherwise the result is written back all or nothing. Writing needs a
   clean git tree (``--allow-dirty`` overrides) so the change is reviewable
   and revertible.
4. Report what was applied, what needs a person (with each migration note)
   and what was skipped.

Run it before raising the karni pin. The CLI carries the changelog, so the
project's old karni is fine.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from karni_cli import project as project_mod
from karni_cli.project import CliError, require_project, venv_python
from karni_cli.upgrades import changelog, engine
from karni_cli.upgrades.codemod import load_codemod

if TYPE_CHECKING:
    from karni.changelog import Change


def _installed_version(project: Path, docker: bool | None, service: str) -> str:
    code = "import karni; print(karni.__version__)"
    mode = project_mod.resolve_execution(project, docker, service)
    if mode == "venv":
        cmd = [str(venv_python(project)), "-c", code]
    else:
        cmd = ["docker", "compose", "exec", "-T", service, "python", "-c", code]
    proc = subprocess.run(cmd, cwd=project, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise CliError(
            "Could not determine the installed karni version "
            f"(exit {proc.returncode}): {proc.stderr.strip()}\n"
            "Pass it instead: karni upgrade --from <version>"
        )
    return proc.stdout.strip()


def _git_status(project: Path) -> list[str] | None:
    """Uncommitted paths under ``project`` (untracked included); None outside git."""
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", "."],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
    )
    if status.returncode != 0:
        return None
    return [line[3:] for line in status.stdout.splitlines() if line.strip()]


def _check_tree(project: Path, allow_dirty: bool) -> None:
    dirty = _git_status(project)
    if dirty is None:
        why = (
            f"{project} is not in a git work tree (or git is not installed). karni upgrade "
            "rewrites source files in place, and without version control nothing shows "
            "or undoes what it changed."
        )
        if not allow_dirty:
            raise CliError(
                f"Refusing to upgrade: {why}\nPreview it with --dry-run, put the project "
                "under git, or pass --allow-dirty to write anyway."
            )
        typer.echo(f"warning: {why} Continuing because of --allow-dirty.", err=True)
        return
    if dirty:
        shown = ", ".join(dirty[:5]) + (f" and {len(dirty) - 5} more" if len(dirty) > 5 else "")
        why = (
            f"the git working tree has uncommitted changes ({shown}). karni upgrade rewrites "
            "files in place; on a clean tree `git diff` shows exactly what it changed and "
            "`git checkout -- .` undoes it, without mixing its edits with yours."
        )
        if not allow_dirty:
            raise CliError(
                f"Refusing to upgrade: {why}\nCommit or stash first, preview with --dry-run, "
                "or pass --allow-dirty."
            )
        typer.echo(f"warning: {why} Continuing because of --allow-dirty.", err=True)


def _list(changes: list[Change]) -> str:
    default = changelog.newest_release(changes)
    lines = [f"Breaking changes this karni-cli knows (default --to: {default}):"]
    release = None
    for change in changes:
        if change.release != release:
            release = change.release
            lines.append(f"\n{release}")
        how = f"codemod {change.codemod}" if change.mechanical else "manual"
        if not change.mechanical and change.codemod:
            how += f", detector {change.codemod}"
        removal = f", removed in {change.removed_in}" if change.removed_in else ""
        arrow = f" -> {change.replacement}" if change.replacement else ""
        lines.append(f"  {change.id}  [{change.kind}, {how}{removal}]")
        lines.append(f"      {change.symbol}{arrow}")
    return "\n".join(lines)


def upgrade(
    to: str | None = typer.Option(
        None,
        "--to",
        metavar="VERSION",
        help="Target Karni version (default: the newest release in the changelog)",
    ),
    from_version: str | None = typer.Option(
        None,
        "--from",
        metavar="VERSION",
        help="The project's current Karni version, instead of asking its interpreter "
        "(use it when the new karni is already installed)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print a unified diff of every change and write nothing"
    ),
    allow_dirty: bool = typer.Option(
        False,
        "--allow-dirty",
        help="Write even with uncommitted changes, or outside a git work tree",
    ),
    list_only: bool = typer.Option(
        False, "--list", help="List every recorded breaking change and exit"
    ),
    docker: bool | None = typer.Option(
        None, "--docker/--no-docker", help="Where to ask for the installed karni version"
    ),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
) -> None:
    """Upgrade the project's code across Karni versions: codemods plus a report."""
    changes = changelog.load()
    if list_only:
        typer.echo(_list(changes))
        return

    project = require_project()
    current = from_version or _installed_version(project, docker, service)
    target = to or changelog.newest_release(changes)
    now, then = (
        changelog.parse(current, "The project's karni version"),
        changelog.parse(target, "--to"),
    )
    if then < now:
        raise CliError(
            f"--to {target} is older than the project's karni {current}; "
            "karni upgrade does not downgrade."
        )
    horizon = changelog.horizon(changes)
    if then > horizon:
        typer.echo(
            f"warning: this karni-cli records changes up to {horizon}; any after that are "
            "not applied. Upgrade karni-cli first (pipx upgrade karni-cli).",
            err=True,
        )
    selected = changelog.select(changes, current, target)
    if not selected:
        typer.echo(f"karni {current} -> {target}: no recorded breaking changes. Nothing to do.")
        return
    if not dry_run:
        _check_tree(project, allow_dirty)

    mechanical = sum(1 for change in selected if change.mechanical)
    typer.echo(
        f"karni {current} -> {target}: {len(selected)} change(s), {mechanical} mechanical, "
        f"{len(selected) - mechanical} manual" + (" (dry run)" if dry_run else "")
    )
    report = engine.run(
        project,
        selected,
        current=current,
        target=target,
        dry_run=dry_run,
        resolve=load_codemod,
    )
    if dry_run and report.changes:
        typer.echo(report.diff, nl=False)
    typer.echo(engine.render(report))
