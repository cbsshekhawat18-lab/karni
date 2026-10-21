"""No karni command ends in an unhandled exception in the states a new project meets.

Every command the Typer app registers runs in four states. The commands are
discovered from the app (groups included; a hidden alias through the command
it aliases), so a new command is covered without editing this file.

- ``no-driver``: DATABASE_URL is PostgreSQL and the project interpreter has no
  psycopg;
- ``db-down``: the driver is installed but the server does not answer;
- ``no-node-modules``: ``frontend/node_modules`` is missing;
- ``no-env``: there is no ``.env``, so DATABASE_URL is the compose default
  (host ``db``, which does not resolve on the host).

The project and the frontend binaries are real files. The project's
processes are emulated where they are launched (``project.run_process``, and
the guard's ``database.probe``), with Django's observed behaviour: without a
driver every Django process dies at startup with a traceback; with the
database down, those that open it do. Long-running commands (serve, worker,
shell, mcp) are exercised with their launch stubbed the same way.

A command passes when no traceback reaches its output and it ends normally,
with a usage error, or with a coded :class:`CliError` (printed by ``karni`` as
``error: C0xx: ... See <docs url>``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from karni_cli import database, mcp_server
from karni_cli import project as project_mod
from karni_cli.commands.new import write_agent_adapters
from karni_cli.main import app
from karni_cli.project import CliError, DatabaseUse

from .conftest import TEMPLATE

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="fake binaries are sh scripts")

STATES = ("no-driver", "db-down", "no-node-modules", "no-env")
DB_DOWN = ("db-down", "no-env")
POSTGRES_URL = "postgres://karni:karni@127.0.0.1:59999/karni"
#: The value passed for every required argument and option.
SAMPLE = "thing"
TRACEBACK = "Traceback (most recent call last)"

#: Django/Celery/pytest programs that open the database as they start, as
#: observed against a real project with the server down.
OPENS_DATABASE = frozenset(
    {
        "migrate",
        "karni_seed",
        "karni_sync_roles",
        "createsuperuser",
        "runserver",
        "showmigrations",
        "beat",
        "pytest",
    }
)


def _discover() -> list[list[str]]:
    """Every command path in the Typer app, groups included, once per implementation.

    A hidden alias (``make:model``) runs the same function as its visible
    name (``make model``), so only the visible one is kept.
    """
    found: list[tuple[list[str], Any]] = []

    def walk(command: Any, path: list[str]) -> None:
        if path:
            found.append((path, command))
        for name, sub in (getattr(command, "commands", None) or {}).items():
            walk(sub, [*path, name])

    walk(typer.main.get_command(app), [])
    seen: set[Any] = set()
    paths: list[list[str]] = []
    for path, command in sorted(found, key=lambda item: bool(item[1].hidden)):
        callback = command.callback
        implementation = getattr(callback, "__wrapped__", callback)
        if implementation is not None and implementation in seen:
            continue
        seen.add(implementation)
        paths.append(path)
    return paths


def _argv(path: list[str]) -> list[str]:
    """``path`` plus a value for each required argument and option."""
    command: Any = typer.main.get_command(app)
    for name in path:
        command = command.commands[name]
    argv = list(path)
    for param in command.params:
        if not param.required:
            continue
        if param.param_type_name == "argument":
            argv.append(SAMPLE)
        else:
            argv += [param.opts[0], SAMPLE]
    return argv


COMMANDS = _discover()
#: Modes a bare invocation does not reach, run in addition to it.
VARIANTS: dict[str, list[list[str]]] = {
    "serve": [["--local"]],
    "manage": [["showmigrations"]],
}
INVOCATIONS = [
    *(_argv(path) for path in COMMANDS),
    *([*name.split(), *extra] for name, extras in VARIANTS.items() for extra in extras),
]


class ProjectWorld:
    """The project's processes in one state (stands in for ``run_process`` and the probe)."""

    def __init__(self, state: str) -> None:
        self.state = state

    def _crash(self, cmd: list[str]) -> str | None:
        """The exception a Django process dies with in this state, if it does."""
        starts_django = "manage.py" in cmd or "pytest" in cmd or "celery" in cmd
        if not starts_django:
            return None
        if self.state == "no-driver":
            return (
                "django.core.exceptions.ImproperlyConfigured: "
                "Error loading psycopg2 or psycopg module"
            )
        if self.state in DB_DOWN and OPENS_DATABASE.intersection(cmd):
            return "django.db.utils.OperationalError: connection failed: Connection refused"
        return None

    def run_process(
        self, cmd: list[str], *, cwd: Path, capture: bool = False
    ) -> subprocess.CompletedProcess[str]:
        crash = self._crash(cmd)
        if crash is not None:
            text = f'{TRACEBACK}:\n  File "manage.py", line 22, in <module>\n{crash}\n'
            if not capture:  # a streamed child writes straight to the terminal
                sys.stderr.write(text)
            return subprocess.CompletedProcess(cmd, 1, "" if capture else None, text)
        if "spectacular" in cmd:  # writes the schema `karni types` reads next
            schema = cwd / cmd[cmd.index("--file") + 1]
            schema.write_text(json.dumps({"openapi": "3.0.3", "info": {}, "paths": {}}))
        return subprocess.CompletedProcess(cmd, 0, "" if capture else None, "")

    def probe(self, project: Path, python: Path, use: DatabaseUse) -> database.Finding | None:
        """What :mod:`karni_cli.db_probe` reports in this state (tested for real elsewhere)."""
        if self.state == "no-driver":
            return database.Finding(
                "driver",
                "default",
                "django.db.backends.postgresql",
                "Error loading psycopg2 or psycopg module",
            )
        if self.state in DB_DOWN and use == "connect":
            host = "db" if self.state == "no-env" else "127.0.0.1"
            return database.Finding(
                "unreachable",
                "default",
                "django.db.backends.postgresql",
                "connection failed: Connection refused",
                host=host,
                port="5432",
                name="karni",
            )
        return None


class _NoRun:
    """An MCP server whose stdio loop is not started (karni mcp runs until stdin closes)."""

    def __init__(self, server: Any) -> None:
        self.server = server

    def run(self) -> None:
        return None


def _script(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One real `karni new` render, copied for every test (commands write to it)."""
    from cookiecutter.main import cookiecutter

    out = tmp_path_factory.mktemp("render")
    cookiecutter(
        str(TEMPLATE),
        no_input=True,
        extra_context={"project_name": "State Check"},
        output_dir=str(out),
    )
    project = out / "state_check"
    write_agent_adapters(project)
    return project


@pytest.fixture
def world(
    request: pytest.FixtureRequest,
    rendered: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ProjectWorld:
    state: str = request.param
    project = tmp_path / "state_check"
    shutil.copytree(rendered, project)
    if state != "no-env":
        url = "sqlite:///db.sqlite3" if state == "no-node-modules" else POSTGRES_URL
        (project / ".env").write_text(f"DATABASE_URL={url}\n")
    if state != "no-node-modules":
        for tool in ("jscpd", "eslint", "openapi-typescript"):
            _script(project / "frontend" / "node_modules" / ".bin" / tool, "exit 0")
    # No network: `karni types` falls back to npx without a local openapi-typescript.
    _script(tmp_path / "bin" / "npx", 'echo "npx: offline in tests" >&2\nexit 1')
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ.get('PATH', '')}")
    monkeypatch.chdir(project)

    emulated = ProjectWorld(state)
    monkeypatch.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))
    monkeypatch.setattr(project_mod, "run_process", emulated.run_process)
    monkeypatch.setattr(database, "probe", emulated.probe)
    real_build = mcp_server.build_server
    monkeypatch.setattr(mcp_server, "build_server", lambda root=None: _NoRun(real_build(root)))
    return emulated


@pytest.mark.parametrize("world", STATES, indirect=True)
@pytest.mark.parametrize("argv", INVOCATIONS, ids=[" ".join(a) for a in INVOCATIONS])
def test_no_command_surfaces_an_unhandled_exception(world: ProjectWorld, argv: list[str]) -> None:
    result = CliRunner().invoke(app, argv)
    shown = f"karni {' '.join(argv)} [{world.state}]"
    assert TRACEBACK not in result.output, f"{shown} let a traceback through:\n{result.output}"
    error = result.exception
    if error is None or isinstance(error, SystemExit):
        return
    assert isinstance(error, CliError) and error.code, (
        f"{shown} raised {error!r}, not a coded CliError:\n{result.output}"
    )


def test_the_discovery_sees_every_kind_of_command() -> None:
    names = {" ".join(path) for path in COMMANDS}
    for expected in ("check", "context", "make", "make model", "rules sync", "schedule run"):
        assert expected in names
    assert "make:model" not in names  # the alias runs `make model`'s function
    assert set(VARIANTS) <= names, "VARIANTS names a command the app no longer has"
