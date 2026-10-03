"""Runner commands: each must run exactly the documented command, through the
project interpreter, streaming output and propagating the exit code.

The subprocess layer is mocked (``project.subprocess.run``), so these tests
assert the precise argv each runner would execute.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli import project as project_mod
from karni_cli.main import app
from karni_cli.project import CliError


class Recorder:
    """Stands in for ``subprocess.run``; records every call."""

    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[dict[str, Any]] = []
        self.returncode = returncode

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, self.returncode, stdout="", stderr="")

    @property
    def cmd(self) -> list[str]:
        assert len(self.calls) == 1, self.calls
        return list(self.calls[0]["cmd"])


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with a .venv (venv mode), cwd inside it, compose not running."""
    (tmp_path / "manage.py").write_text("")
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: False)
    return tmp_path


@pytest.fixture
def docker_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project without a .venv whose compose stack is running (docker mode)."""
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: True)
    return tmp_path


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(project_mod.subprocess, "run", recorder)
    return recorder


def _py(project: Path) -> str:
    return str(project / ".venv" / "bin" / "python")


def _invoke(runner: CliRunner, *args: str) -> Any:
    return runner.invoke(app, list(args))


# --- venv mode: the exact command per runner ----------------------------------

VENV_CASES: list[tuple[list[str], list[str]]] = [
    (["migrate"], ["manage.py", "migrate"]),
    (["migrate", "events", "0003", "--plan"], ["manage.py", "migrate", "events", "0003", "--plan"]),
    (["test"], ["-m", "pytest"]),
    (
        ["test", "tests/test_api.py", "-x", "-k", "create or update", "--lf"],
        ["-m", "pytest", "tests/test_api.py", "-x", "-k", "create or update", "--lf"],
    ),
    (["test", "--", "--help"], ["-m", "pytest", "--help"]),
    (["shell"], ["manage.py", "shell"]),
    (["shell", "-c", "print(1)"], ["manage.py", "shell", "-c", "print(1)"]),
    (["routes"], ["manage.py", "karni_routes"]),
    (["routes", "--json"], ["manage.py", "karni_routes", "--json"]),
    (["worker"], ["-m", "celery", "-A", "config", "worker", "-l", "info"]),
    (
        ["worker", "-A", "proj", "-l", "debug", "-Q", "high,low", "--concurrency=2"],
        [
            "-m",
            "celery",
            "-A",
            "proj",
            "worker",
            "-l",
            "debug",
            "-Q",
            "high,low",
            "--concurrency=2",
        ],
    ),
    (["beat"], ["-m", "celery", "-A", "config", "beat", "-l", "info"]),
    (["beat", "--loglevel", "warning"], ["-m", "celery", "-A", "config", "beat", "-l", "warning"]),
    (["schedule", "list"], ["manage.py", "karni_schedules"]),
    (["schedule", "list", "--json"], ["manage.py", "karni_schedules", "--json"]),
    (
        ["schedule", "run", "nightly-report"],
        ["manage.py", "karni_schedules", "--run", "nightly-report"],
    ),
    (["seed"], ["manage.py", "karni_seed"]),
    (
        ["seed", "--count", "20", "--seed", "42", "--reset", "--model", "events.Event"],
        [
            "manage.py",
            "karni_seed",
            "--count",
            "20",
            "--seed",
            "42",
            "--reset",
            "--model",
            "events.Event",
        ],
    ),
    (["createsuperuser"], ["manage.py", "createsuperuser"]),
    (
        ["createsuperuser", "--email", "a@example.com", "--noinput"],
        ["manage.py", "createsuperuser", "--email", "a@example.com", "--noinput"],
    ),
    (["manage", "showmigrations", "events"], ["manage.py", "showmigrations", "events"]),
    (["manage", "check", "--deploy"], ["manage.py", "check", "--deploy"]),
    (["manage", "--", "migrate", "--help"], ["manage.py", "migrate", "--help"]),
    (["manage"], ["manage.py"]),
    (["serve", "--local"], ["manage.py", "runserver", "127.0.0.1:8000"]),
    (
        ["serve", "--local", "--host", "0.0.0.0", "--port", "9000"],
        ["manage.py", "runserver", "0.0.0.0:9000"],
    ),
]


@pytest.mark.parametrize(("argv", "expected"), VENV_CASES)
def test_runner_runs_the_documented_command(
    runner: CliRunner, project: Path, run: Recorder, argv: list[str], expected: list[str]
) -> None:
    result = _invoke(runner, *argv)
    assert result.exit_code == 0, result.output
    assert run.cmd == [_py(project), *expected]
    call = run.calls[0]
    assert call["cwd"] == project
    assert call["capture_output"] is False  # output streams to the terminal


@pytest.mark.parametrize(
    "argv", [["migrate"], ["test"], ["schedule", "run", "x"], ["manage", "x"], ["seed"]]
)
def test_runner_propagates_the_exit_code(
    runner: CliRunner, project: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    monkeypatch.setattr(project_mod.subprocess, "run", Recorder(returncode=3))
    assert _invoke(runner, *argv).exit_code == 3


# --- docker mode --------------------------------------------------------------


def test_docker_mode_execs_in_the_compose_service(
    runner: CliRunner, docker_project: Path, run: Recorder
) -> None:
    result = _invoke(runner, "migrate", "--service", "web")
    assert result.exit_code == 0, result.output
    assert run.cmd == ["docker", "compose", "exec", "-T", "web", "python", "manage.py", "migrate"]


def test_interactive_runners_get_a_tty_in_a_terminal(
    runner: CliRunner, docker_project: Path, run: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_mod, "_tty", lambda: True)
    for argv, tail in [
        (["shell"], ["manage.py", "shell"]),
        (["test", "-x"], ["-m", "pytest", "-x"]),
        (["createsuperuser"], ["manage.py", "createsuperuser"]),
        (["worker"], ["-m", "celery", "-A", "config", "worker", "-l", "info"]),
        (["manage", "dbshell"], ["manage.py", "dbshell"]),
    ]:
        run.calls.clear()
        assert _invoke(runner, *argv).exit_code == 0
        assert run.cmd == ["docker", "compose", "exec", "django", "python", *tail]


def test_machine_output_runners_never_get_a_tty(
    runner: CliRunner, docker_project: Path, run: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_mod, "_tty", lambda: True)
    for argv in (["routes", "--json"], ["schedule", "list", "--json"], ["migrate"]):
        run.calls.clear()
        assert _invoke(runner, *argv).exit_code == 0
        assert run.cmd[:5] == ["docker", "compose", "exec", "-T", "django"]


def test_without_a_terminal_interactive_runners_keep_dash_t(
    runner: CliRunner, docker_project: Path, run: Recorder
) -> None:
    # CliRunner swaps in non-TTY streams, as an agent's subprocess would.
    assert _invoke(runner, "shell").exit_code == 0
    assert run.cmd == ["docker", "compose", "exec", "-T", "django", "python", "manage.py", "shell"]


def test_explicit_no_docker_wins_over_a_running_stack(
    runner: CliRunner, project: Path, run: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: True)
    assert _invoke(runner, "routes", "--no-docker").exit_code == 0
    assert run.cmd == [_py(project), "manage.py", "karni_routes"]


# --- serve --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["serve"], ["docker", "compose", "up"]),
        (["serve", "--build", "-d"], ["docker", "compose", "up", "--build", "--detach"]),
    ],
)
def test_serve_runs_docker_compose_up(
    runner: CliRunner, project: Path, run: Recorder, argv: list[str], expected: list[str]
) -> None:
    result = _invoke(runner, *argv)
    assert result.exit_code == 0, result.output
    assert run.cmd == expected
    assert run.calls[0]["cwd"] == project


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["serve", "--local", "--build"], "apply to docker compose"),
        (["serve", "--port", "9000"], "need --local"),
    ],
)
def test_serve_rejects_mismatched_options(
    runner: CliRunner, project: Path, run: Recorder, argv: list[str], message: str
) -> None:
    result = _invoke(runner, *argv)
    assert isinstance(result.exception, CliError)
    assert message in str(result.exception)
    assert run.calls == []


def test_serve_local_needs_a_venv(runner: CliRunner, docker_project: Path, run: Recorder) -> None:
    result = _invoke(runner, "serve", "--local")
    assert isinstance(result.exception, CliError)
    assert ".venv" in str(result.exception) and "drop --local" in str(result.exception)
    assert run.calls == []


def test_serve_without_docker_names_the_alternative(
    runner: CliRunner, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("docker")

    monkeypatch.setattr(project_mod.subprocess, "run", missing)
    result = _invoke(runner, "serve")
    assert isinstance(result.exception, CliError)
    assert "karni serve --local" in str(result.exception)


# --- help and principles ------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "wraps"),
    [
        (["serve"], "docker compose up"),
        (["migrate"], "manage.py migrate"),
        (["test"], "python -m pytest"),
        (["shell"], "manage.py shell"),
        (["routes"], "manage.py karni_routes"),
        (["worker"], "celery -A config worker"),
        (["beat"], "celery -A config beat"),
        (["schedule"], "manage.py karni_schedules"),
        (["schedule", "list"], "manage.py karni_schedules"),
        (["schedule", "run"], "karni_schedules --run NAME"),
        (["createsuperuser"], "manage.py createsuperuser"),
        (["seed"], "manage.py karni_seed [ARGS]"),
        (["manage"], "manage.py ARGS"),
    ],
)
def test_help_states_what_each_runner_wraps(runner: CliRunner, argv: list[str], wraps: str) -> None:
    result = runner.invoke(app, [*argv, "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert wraps in result.output


def test_runners_outside_a_project_fail_cleanly(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run: Recorder
) -> None:
    monkeypatch.chdir(tmp_path)
    result = _invoke(runner, "migrate")
    assert isinstance(result.exception, CliError)
    assert run.calls == []


def test_the_cli_never_imports_django() -> None:
    code = "import sys, karni_cli.main; sys.exit('django' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
