"""Project discovery and manage.py execution.

The CLI never imports Django. Everything project-side runs through the
project's own interpreter, resolved in this order (per command flags):
explicit ``--docker/--no-docker`` > ``<project>/.venv`` > a running docker
compose service > a two-line error naming both remedies.

Interactive runners (shell, test, worker, ...) pass ``interactive=True``:
in docker mode that allocates a TTY (``docker compose exec`` without
``-T``) when the CLI itself runs in a terminal, so prompts, colours and
Ctrl-C work; scripted and agent runs (no TTY) keep ``-T``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

#: Typer ``context_settings`` for runners that pass unknown options through
#: to the wrapped command (``karni test -x -k name``). Put ``--`` before
#: arguments that clash with the runner's own options.
PASSTHROUGH: dict[str, Any] = {"ignore_unknown_options": True, "allow_extra_args": True}


class CliError(Exception):
    """User-facing CLI failure; the message is printed without a traceback.

    ``code`` is a registered code (``C101``, or a Karni code such as ``E704``
    passed through); ``str()`` is ``"<code>: <message> See <docs url>"`` and
    ``karni explain <code>`` prints the full entry offline.
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:
        if not self.code:
            return self.message
        from karni_cli.errorcodes import docs_url

        sep = "\n" if "\n" in self.message else " "
        return f"{self.code}: {self.message}{sep}See {docs_url(self.code)}"


def find_project(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (default cwd) to the directory holding manage.py."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "manage.py").is_file():
            return candidate
    return None


def require_project(start: Path | None = None) -> Path:
    project = find_project(start)
    if project is None:
        raise CliError(
            "No manage.py found here or above — run inside a Karni project.", code="C001"
        )
    return project


def venv_python(project: Path) -> Path | None:
    python = project / ".venv" / "bin" / "python"
    return python if python.exists() else None


def compose_service_running(project: Path, service: str) -> bool:
    """True when ``docker compose ps`` reports the service as running."""
    try:
        proc = subprocess.run(
            ["docker", "compose", "ps", "--status", "running", "--services"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    if proc.returncode != 0:
        return False
    return service in proc.stdout.split()


def resolve_execution(project: Path, docker: bool | None, service: str) -> str:
    """Pick "venv" or "docker" per the documented resolution order."""
    if docker is True:
        if not compose_service_running(project, service):
            raise CliError(
                f'docker compose service "{service}" is not running.\n'
                "Start the stack first: docker compose up -d",
                code="C002",
            )
        return "docker"
    if docker is False:
        if venv_python(project) is None:
            raise CliError(
                "No .venv found in the project (and --no-docker was given).\n"
                "Create one (uv venv && uv pip install -r pyproject.toml) or drop --no-docker.",
                code="C002",
            )
        return "venv"
    if venv_python(project) is not None:
        return "venv"
    if compose_service_running(project, service):
        return "docker"
    raise CliError(
        "No way to run the project: no .venv and the compose stack is not running.\n"
        "Either `docker compose up -d`, or create a venv "
        "(uv venv && uv pip install -r pyproject.toml).",
        code="C002",
    )


def _tty() -> bool:
    """True when the CLI runs in a terminal (both stdin and stdout)."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def python_command(
    project: Path,
    args: list[str],
    *,
    docker: bool | None = None,
    service: str = "django",
    interactive: bool = False,
) -> list[str]:
    """The argv running ``python <args>`` in the resolved environment."""
    mode = resolve_execution(project, docker, service)
    if mode == "venv":
        return [str(venv_python(project)), *args]
    no_tty = [] if interactive and _tty() else ["-T"]
    return ["docker", "compose", "exec", *no_tty, service, "python", *args]


def run_python(
    project: Path,
    args: list[str],
    *,
    docker: bool | None = None,
    service: str = "django",
    capture: bool = True,
    interactive: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run ``python <args>`` through the project interpreter, cwd pinned to the project.

    Returns the CompletedProcess (text mode, never raises on non-zero exit).
    With ``capture=False`` output streams through to the terminal (stdin is
    always inherited); ``interactive=True`` also asks docker for a TTY.
    """
    cmd = python_command(project, args, docker=docker, service=service, interactive=interactive)
    return subprocess.run(cmd, cwd=project, text=True, capture_output=capture, check=False)


def run_manage(
    project: Path,
    args: list[str],
    *,
    docker: bool | None = None,
    service: str = "django",
    capture: bool = True,
    interactive: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run ``manage.py <args>`` in the resolved environment (see :func:`run_python`)."""
    return run_python(
        project,
        ["manage.py", *args],
        docker=docker,
        service=service,
        capture=capture,
        interactive=interactive,
    )


def run_compose(project: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``docker compose <args>`` in the project, streaming to the terminal."""
    try:
        return subprocess.run(["docker", "compose", *args], cwd=project, text=True, check=False)
    except FileNotFoundError:
        raise CliError(
            "docker not found — install Docker with the compose plugin, "
            "or run without it: karni serve --local",
            code="C003",
        ) from None
