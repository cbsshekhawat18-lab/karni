"""Project discovery and manage.py execution.

The CLI never imports Django. Everything project-side runs through the
project's own interpreter, resolved in this order (per command flags):
explicit ``--docker/--no-docker`` > ``<project>/.venv`` > a running docker
compose service > a two-line error naming both remedies.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class CliError(Exception):
    """User-facing CLI failure; the message is printed without a traceback."""


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
        raise CliError("No manage.py found here or above — run inside a Karni project.")
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
                "Start the stack first: docker compose up -d"
            )
        return "docker"
    if docker is False:
        if venv_python(project) is None:
            raise CliError(
                "No .venv found in the project (and --no-docker was given).\n"
                "Create one (uv venv && uv pip install -r pyproject.toml) or drop --no-docker."
            )
        return "venv"
    if venv_python(project) is not None:
        return "venv"
    if compose_service_running(project, service):
        return "docker"
    raise CliError(
        "No way to run the project: no .venv and the compose stack is not running.\n"
        "Either `docker compose up -d`, or create a venv "
        "(uv venv && uv pip install -r pyproject.toml)."
    )


def run_manage(
    project: Path,
    args: list[str],
    *,
    docker: bool | None = None,
    service: str = "django",
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run ``manage.py <args>`` in the resolved environment, cwd pinned to the project.

    Returns the CompletedProcess (text mode, never raises on non-zero exit).
    With ``capture=False`` output streams through to the terminal.
    """
    mode = resolve_execution(project, docker, service)
    if mode == "venv":
        cmd = [str(venv_python(project)), "manage.py", *args]
    else:
        cmd = ["docker", "compose", "exec", "-T", service, "python", "manage.py", *args]
    return subprocess.run(cmd, cwd=project, text=True, capture_output=capture, check=False)
