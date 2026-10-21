"""Project discovery and manage.py execution.

The CLI never imports Django. Everything project-side runs through the
project's own interpreter, resolved in this order (per command flags):
explicit ``--docker/--no-docker`` > ``<project>/.venv`` > a running docker
compose service > a two-line error naming both remedies.

Interactive runners (shell, test, worker, ...) pass ``interactive=True``:
in docker mode that allocates a TTY (``docker compose exec`` without
``-T``) when the CLI itself runs in a terminal, so prompts, colours and
Ctrl-C work; scripted and agent runs (no TTY) keep ``-T``.

Runners that start Django declare what they need from its database with
``database=`` (``run_manage`` defaults to ``"load"``): the guard in
:mod:`karni_cli.database` turns a missing driver or an unreachable database
into a coded error (C012, C013) instead of Django's traceback.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

#: Typer ``context_settings`` for runners that pass unknown options through
#: to the wrapped command (``karni test -x -k name``). Put ``--`` before
#: arguments that clash with the runner's own options.
PASSTHROUGH: dict[str, Any] = {"ignore_unknown_options": True, "allow_extra_args": True}

#: What a command needs from the project's database (:mod:`karni_cli.database`):
#: ``"load"`` its backend and driver (every Django process), ``"connect"`` a
#: running server too.
DatabaseUse = Literal["load", "connect"]


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
    """The project's interpreter: its ``.venv``, else the active virtualenv, else this one.

    ``VIRTUAL_ENV`` covers the host setup where one activated venv holds
    karni-cli and the project's dependencies (the quickstart). The interpreter
    running karni-cli counts when it has Django and karni installed — the
    quickstart's venv invoked by path, an MCP host that inherited no
    ``VIRTUAL_ENV``. A pipx-installed ``karni`` has neither and keeps looking
    for the project's own.
    """
    python = project / ".venv" / "bin" / "python"
    if python.exists():
        return python
    active = os.environ.get("VIRTUAL_ENV")
    if active:
        candidate = Path(active) / "bin" / "python"
        if candidate.exists():
            return candidate
    return _running_interpreter()


def _running_interpreter() -> Path | None:
    """``sys.executable`` when it can import Django and karni (never imported here)."""
    if importlib.util.find_spec("django") is None or importlib.util.find_spec("karni") is None:
        return None
    return Path(sys.executable)


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
                "No .venv in the project and no active virtualenv (and --no-docker was given).\n"
                "Create one (python -m venv .venv && .venv/bin/pip install -e .), activate one "
                "that has the project's dependencies, or drop --no-docker.",
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


def _resolve_command(
    project: Path, args: list[str], *, docker: bool | None, service: str, interactive: bool
) -> tuple[Path | None, list[str]]:
    """The host interpreter (``None`` in docker mode) and the argv running ``python <args>``."""
    if resolve_execution(project, docker, service) == "venv":
        python = venv_python(project)
        return python, [str(python), *args]
    no_tty = [] if interactive and _tty() else ["-T"]
    return None, ["docker", "compose", "exec", *no_tty, service, "python", *args]


def python_command(
    project: Path,
    args: list[str],
    *,
    docker: bool | None = None,
    service: str = "django",
    interactive: bool = False,
) -> list[str]:
    """The argv running ``python <args>`` in the resolved environment."""
    _, cmd = _resolve_command(
        project, args, docker=docker, service=service, interactive=interactive
    )
    return cmd


def run_python(
    project: Path,
    args: list[str],
    *,
    docker: bool | None = None,
    service: str = "django",
    capture: bool = True,
    interactive: bool = False,
    database: DatabaseUse | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``python <args>`` through the project interpreter, cwd pinned to the project.

    Returns the CompletedProcess (text mode, never raises on non-zero exit).
    With ``capture=False`` output streams through to the terminal (stdin is
    always inherited); ``interactive=True`` also asks docker for a TTY.

    ``database`` is what the command needs from the project's database (it
    starts Django): :func:`karni_cli.database.guard` checks it on the host
    before a streamed command and after a captured one that failed, and raises
    a coded :class:`CliError` (C012/C013) instead of letting Django's
    traceback through. ``None`` (the default here) skips the check.
    """
    python, cmd = _resolve_command(
        project, args, docker=docker, service=service, interactive=interactive
    )
    if database is None or python is None:
        return run_process(cmd, cwd=project, capture=capture)
    from karni_cli import database as database_mod

    checked = database_mod.enabled()
    if checked and not capture:
        database_mod.guard(project, python, database)
    proc = run_process(cmd, cwd=project, capture=capture)
    if checked and capture and proc.returncode != 0:
        database_mod.guard(project, python, database)
    return proc


def run_process(
    cmd: list[str], *, cwd: Path, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    """``subprocess.run`` that passes SIGTERM on to the child.

    ``karni serve`` and ``karni worker`` wrap a real server: a script or an
    agent that stops the wrapper must stop the server too, not leak it.
    Ctrl-C needs no forwarding (the terminal signals the whole group).
    """
    pipe = subprocess.PIPE if capture else None
    with subprocess.Popen(cmd, cwd=cwd, text=True, stdout=pipe, stderr=pipe) as proc:

        def forward(signum: int, _frame: Any) -> None:
            with contextlib.suppress(ProcessLookupError):
                proc.send_signal(signum)

        previous: Any = None
        try:
            previous = signal.signal(signal.SIGTERM, forward)
        except ValueError:  # not the main thread: no forwarding, same run
            previous = None
        try:
            out, err = proc.communicate()
        except KeyboardInterrupt:
            proc.wait()
            raise
        finally:
            if previous is not None:
                signal.signal(signal.SIGTERM, previous)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def run_manage(
    project: Path,
    args: list[str],
    *,
    docker: bool | None = None,
    service: str = "django",
    capture: bool = True,
    interactive: bool = False,
    database: DatabaseUse | None = "load",
) -> subprocess.CompletedProcess[str]:
    """Run ``manage.py <args>`` in the resolved environment (see :func:`run_python`).

    Every manage.py command starts Django, so ``database`` defaults to
    ``"load"``; commands that open the database pass ``"connect"``.
    """
    return run_python(
        project,
        ["manage.py", *args],
        docker=docker,
        service=service,
        capture=capture,
        interactive=interactive,
        database=database,
    )


def run_compose(project: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``docker compose <args>`` in the project, streaming to the terminal."""
    try:
        return run_process(["docker", "compose", *args], cwd=project)
    except FileNotFoundError:
        raise CliError(
            "docker not found — install Docker with the compose plugin, "
            "or run without it: karni serve --local",
            code="C003",
        ) from None
