"""``karni doctor`` — a human-readable report on the environment karni sees.

One line per fact: the project, how project commands would run (``.venv`` or
a running compose service), the database and Redis the project's settings
name and whether they answer (:mod:`karni_cli.services`), Node/npm (flagged
below the floors in :mod:`karni_cli.toolchain`), the ``@karni/ui`` manifest
behind ``karni context``'s COMPONENTS/HOOKS, whether the agent adapters are
fresh, and which history providers are installed / detect a store. It
reports and never changes anything; the exit status is 0 unless the CLI
itself fails.

When ``.env`` still names the docker compose hosts (``db``, ``redis``) and
they do not resolve on this machine, doctor looks for a local PostgreSQL and
Redis and prints the exact ``.env`` lines (and the ``createdb`` command) that
use them.

It may end with ONE tip (see :mod:`karni_cli.tips`); ``-q`` suppresses it.
This is human output — never parse it; agents use ``karni context``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import typer

from karni_cli import agent_data, envfile, services, tips, toolchain
from karni_cli import history as history_mod
from karni_cli import project as project_mod
from karni_cli import suggest as suggest_mod
from karni_cli.adapters import DEPRECATED_CODE, sync
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
        "none. Create .venv (python -m venv .venv && .venv/bin/pip install -e .), activate a "
        "virtualenv with the project's dependencies, or start the stack (docker compose up -d)"
    )


#: Karni's defaults (karni.conf.base) when DATABASE_URL / REDIS_URL are unset.
DEFAULT_URLS: dict[services.Kind, str] = {
    "postgres": "postgres://karni:karni@db:5432/karni",
    "redis": "redis://redis:6379/0",
}
_VARIABLE: dict[services.Kind, str] = {"postgres": "DATABASE_URL", "redis": "REDIS_URL"}
_NAME: dict[services.Kind, str] = {"postgres": "PostgreSQL", "redis": "Redis"}
_START: dict[services.Kind, str] = {
    "postgres": (
        "Start one with `brew services start postgresql@16` on macOS or `sudo apt install "
        "postgresql` on Linux, or run the compose database: `docker compose up -d --wait db`"
    ),
    "redis": (
        "Start one with `brew services start redis` on macOS or `sudo apt install "
        "redis-server` on Linux. Or set KARNI_CACHE=locmem for the cache (Celery still "
        "needs Redis)"
    ),
}


def _masked(url: str) -> str:
    """``url`` with its password replaced by ``***``."""
    try:
        password = urlsplit(url).password
    except ValueError:
        return url
    return url.replace(f":{password}@", ":***@", 1) if password else url


def _use_local(
    kind: services.Kind, port: int, database: str, configured: services.Endpoint | None
) -> list[str]:
    lines = services.env_lines(kind, port, database=database, configured=configured)
    out = [f"{_NAME[kind]} answers on 127.0.0.1:{port}. To use it, put this line in .env:"]
    out.append(f"  {lines[0]}")
    if len(lines) > 1:
        out.append(f"and create the database once: {lines[1]}")
    return out


def _service(
    project: Path, kind: services.Kind, file: dict[str, str], *, on_host: bool, database: str
) -> list[str]:
    """What the project's ``DATABASE_URL`` or ``REDIS_URL`` names, and whether it answers."""
    variable = _VARIABLE[kind]
    found = envfile.lookup(project, variable, file)
    url, origin = (
        (found.text, found.origin) if found and found.text else (DEFAULT_URLS[kind], "default")
    )
    head = f"{variable} ({origin}) {_masked(url)}"
    if kind == "postgres" and url.startswith("sqlite"):
        return [f"{head}: SQLite, no server"]
    endpoint = services.parse(kind, url)
    if endpoint is None:
        return [f"{head}: not a {_NAME[kind]} URL, not checked"]
    compose = endpoint.host == services.COMPOSE_HOSTS[kind]
    if compose and not on_host:
        return [f"{head}: the docker compose service (project commands run in the stack)"]
    if services.resolves(endpoint.host):
        answer = services.speaks(kind, endpoint.host, endpoint.port)
        if answer:
            return [f"{head}: {_NAME[kind]} answers"]
        what = (
            "nothing answers" if answer is None else f"a service that is not {_NAME[kind]} answers"
        )
        lines = [f"{head}: {what} at {endpoint.host}:{endpoint.port}"]
    else:
        reason = (
            ": it is the docker compose service, reachable only inside the stack" if compose else ""
        )
        lines = [f"{head}: {endpoint.host} does not resolve here{reason}"]
    local = services.find_local(kind, endpoint.port)
    if local is None:
        lines.append(
            f"No {_NAME[kind]} answers on 127.0.0.1:{services.DEFAULT_PORTS[kind]}. {_START[kind]}"
        )
    else:
        lines += _use_local(kind, local, database, endpoint)
    return lines


def _services(project: Path, service: str) -> tuple[list[str], list[str]]:
    """The ``database`` and ``redis`` lines."""
    file = envfile.read(project)
    on_host = project_mod.venv_python(
        project
    ) is not None or not project_mod.compose_service_running(project, service)
    name = envfile.lookup(project, "PROJECT_NAME", file)
    database = services.database_name(project, name.text if name else None)
    return (
        _service(project, "postgres", file, on_host=on_host, database=database),
        _service(project, "redis", file, on_host=on_host, database=database),
    )


def _node() -> list[str]:
    """The Node and npm on PATH, then one line with the fix when either is below the floor."""
    node = tool_version("node")
    if node is None:
        return ["not found (needed for the frontend and `karni types`)"]
    npm = tool_version("npm")
    lines = [f"{node} (npm {npm})" if npm else f"{node} (npm not found)"]
    problem = toolchain.shortfall(node, npm)
    if problem is not None:
        lines.append(f"too old: {problem}")
    return lines


def _echo_lines(label: str, lines: list[str]) -> None:
    for i, text in enumerate(lines):
        typer.echo(_line(label if i == 0 else "", text))


def _manifest(project: Path) -> str:
    found = find_manifest(project, None)
    if found is None:
        return (
            "@karni/ui manifest absent (COMPONENTS/HOOKS hidden). "
            f"Run `npm install` in frontend/ with npm {toolchain.NPM_FLOOR_TEXT} or later"
        )
    return f"@karni/ui manifest: {_display(found, project)}"


def _adapters(project: Path) -> list[str]:
    try:
        result = sync(project, agent_data.load(project), check=True)
    except CliError as exc:
        return [f"cannot check: {exc}"]
    if result.stale:
        lines = [f"stale ({len(result.stale)} files). Run `karni rules sync`"]
    else:
        lines = [f"up to date ({len(result.unchanged)} files)"]
    if result.deprecated:
        lines.append(
            f"{DEPRECATED_CODE}: {len(result.deprecated)} tool-specific files are deprecated and "
            "removed in 1.0. Keep AGENTS.md (`karni rules sync` names them)"
        )
    return lines


def _history(project: Path) -> list[str]:
    found = history_mod.discovered()
    if found is None:
        return ["unavailable (karni.agent.history not found)"]
    detected = history_mod.detected_names(project)
    lines = (
        [f"{name}: store detected (use `karni context --with-history FILE`)" for name in detected]
        if detected
        else [f"no store detected (installed: {', '.join(found.names) or 'none'})"]
    )
    lines += [f"skipped provider {error}" for error in found.errors]
    return lines


def _suggestions(project: Path, service: str) -> list[str]:
    """Experimental. The suggestions of ``karni suggest``, as doctor's lines (never an error)."""
    try:
        try:
            core = suggest_mod.core_suggestions(project, service=service)
        except CliError:
            core = None
        data = suggest_mod.collect(project, core, service=service)
    except Exception:  # noqa: BLE001 - a suggestion must never break karni doctor
        return []
    if not data["enabled"]:
        return [_line("suggestions", "off (KARNI_SUGGESTIONS = False)")]
    if not data["suggestions"]:
        return [_line("suggestions", "none")]
    return [
        _line("suggestions", f"{len(data['suggestions'])}, they never fail a run"),
        "",
        *suggest_mod.render(data).splitlines()[1:],
    ]


def doctor(
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Do not print the optional tip."),
) -> None:
    project = find_project()
    if project is None:
        typer.echo(_line("project", "not found (no manage.py here or above)"))
        _echo_lines("node", _node())
        return
    typer.echo(_line("project", str(project)))
    typer.echo(_line("interpreter", _interpreter(project, service)))
    database, redis = _services(project, service)
    _echo_lines("database", database)
    _echo_lines("redis", redis)
    _echo_lines("node", _node())
    typer.echo(_line("ui", _manifest(project)))
    _echo_lines("adapters", _adapters(project))
    _echo_lines("history", _history(project))
    for line in _suggestions(project, service):
        typer.echo(line)
    tip = tips.history_tip(project, quiet=quiet)
    if tip:
        typer.echo("")
        typer.echo(tip)
