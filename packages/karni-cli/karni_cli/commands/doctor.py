"""``karni doctor`` — a human-readable report on the environment karni sees.

One line per fact: the project, how project commands would run (``.venv`` or
a running compose service), Node/npm, the ``@karni/ui`` manifest behind
``karni context``'s COMPONENTS/HOOKS, whether the agent adapters are fresh,
and which history providers are installed / detect a store. It reports and
never changes anything; the exit status is 0 unless the CLI itself fails.

It may end with ONE tip (see :mod:`karni_cli.tips`); ``-q`` suppresses it.
This is human output — never parse it; agents use ``karni context``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer

from karni_cli import agent_data, tips
from karni_cli import history as history_mod
from karni_cli import project as project_mod
from karni_cli.adapters import sync
from karni_cli.commands.context import find_manifest
from karni_cli.project import CliError, find_project

_WIDTH = 12


def _line(label: str, text: str) -> str:
    return f"{label:<{_WIDTH}}{text}"


def tool_version(name: str) -> str | None:
    """``<name> --version`` output, or ``None`` when absent or failing."""
    executable = shutil.which(name)
    if executable is None:
        return None
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = proc.stdout.strip().splitlines()
    return out[0] if proc.returncode == 0 and out else None


def _display(path: Path, project: Path) -> str:
    """``path`` relative to the project when it lives inside it, else as given.

    The quickstart's layout keeps the venv one level above the project.
    """
    try:
        return str(path.relative_to(project))
    except ValueError:
        return str(path)


def _interpreter(project: Path, service: str) -> str:
    python = project_mod.venv_python(project)
    if python is not None:
        return f"{_display(python, project)} (project commands run here)"
    if project_mod.compose_service_running(project, service):
        return f'docker compose service "{service}" (running)'
    return (
        "none — create .venv (python -m venv .venv && .venv/bin/pip install -e .), activate a "
        "virtualenv with the project's dependencies, or start the stack (docker compose up -d)"
    )


def _node() -> str:
    node = tool_version("node")
    if node is None:
        return "not found — needed for the frontend and `karni types`"
    npm = tool_version("npm")
    return f"{node} (npm {npm})" if npm else f"{node} (npm not found)"


def _manifest(project: Path) -> str:
    found = find_manifest(project, None)
    if found is None:
        return "@karni/ui manifest absent — `npm install` in frontend/ (COMPONENTS/HOOKS hidden)"
    return f"@karni/ui manifest: {_display(found, project)}"


def _adapters(project: Path) -> str:
    try:
        result = sync(project, agent_data.load(project), check=True)
    except CliError as exc:
        return f"cannot check: {exc}"
    if result.stale:
        return f"stale ({len(result.stale)} files) — run `karni rules sync`"
    return f"up to date ({len(result.unchanged)} files)"


def _history(project: Path) -> list[str]:
    found = history_mod.discovered()
    if found is None:
        return ["unavailable (karni.agent.history not found)"]
    detected = history_mod.detected_names(project)
    lines = (
        [f"{name}: store detected — `karni context --with-history FILE`" for name in detected]
        if detected
        else [f"no store detected (installed: {', '.join(found.names) or 'none'})"]
    )
    lines += [f"skipped provider {error}" for error in found.errors]
    return lines


def doctor(
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Do not print the optional tip."),
) -> None:
    project = find_project()
    if project is None:
        typer.echo(_line("project", "not found (no manage.py here or above)"))
        typer.echo(_line("node", _node()))
        return
    typer.echo(_line("project", str(project)))
    typer.echo(_line("interpreter", _interpreter(project, service)))
    typer.echo(_line("node", _node()))
    typer.echo(_line("ui", _manifest(project)))
    typer.echo(_line("adapters", _adapters(project)))
    for i, text in enumerate(_history(project)):
        typer.echo(_line("history" if i == 0 else "", text))
    tip = tips.history_tip(project, quiet=quiet)
    if tip:
        typer.echo("")
        typer.echo(tip)
