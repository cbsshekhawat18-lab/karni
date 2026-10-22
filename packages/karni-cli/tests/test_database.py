"""The database guard (karni_cli.database): when it runs, what the probe finds, what it says."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli import database, db_probe
from karni_cli import project as project_mod
from karni_cli.errorcodes import docs_url
from karni_cli.main import app
from karni_cli.project import CliError, run_manage, run_python

DRIVER = database.Finding(
    "driver", "default", "django.db.backends.postgresql", "Error loading psycopg2 or psycopg module"
)
DOWN = database.Finding(
    "unreachable",
    "default",
    "django.db.backends.postgresql",
    "connection failed: Connection refused.",
    host="127.0.0.1",
    port="5432",
    name="karni",
)
HIDE_POSTGRES_DRIVERS = 'raise ImportError("hidden by the test: no PostgreSQL driver")\n'


class Calls:
    """Records the guard's probes and the project processes, in order."""

    def __init__(self, finding: database.Finding | None, returncode: int = 0) -> None:
        self.finding = finding
        self.returncode = returncode
        self.log: list[str] = []

    def probe(self, project: Path, python: Path, use: str) -> database.Finding | None:
        self.log.append(f"probe:{use}")
        return self.finding

    def run_process(
        self, cmd: list[str], *, cwd: Path, capture: bool = False
    ) -> subprocess.CompletedProcess[str]:
        self.log.append("run")
        return subprocess.CompletedProcess(cmd, self.returncode, "", "Traceback ...")


@pytest.fixture
def host_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project whose commands run on the host (a .venv interpreter)."""
    (tmp_path / "manage.py").write_text("")
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: False)
    return tmp_path


def _install(monkeypatch: pytest.MonkeyPatch, calls: Calls) -> Calls:
    monkeypatch.setattr(database, "probe", calls.probe)
    monkeypatch.setattr(project_mod, "run_process", calls.run_process)
    return calls


# when the guard runs


def test_a_streamed_command_is_checked_before_it_starts(host_project, monkeypatch) -> None:
    calls = _install(monkeypatch, Calls(DRIVER))
    with pytest.raises(CliError) as exc:
        run_manage(host_project, ["migrate"], capture=False, database="connect")
    assert exc.value.code == "C012"
    assert calls.log == ["probe:connect"]  # Django never started: no traceback printed


def test_a_captured_command_is_checked_only_after_it_failed(host_project, monkeypatch) -> None:
    calls = _install(monkeypatch, Calls(DRIVER, returncode=0))
    assert run_manage(host_project, ["karni_context"]).returncode == 0
    assert calls.log == ["run"]  # a working project pays nothing

    calls = _install(monkeypatch, Calls(DRIVER, returncode=1))
    with pytest.raises(CliError, match="C012"):
        run_manage(host_project, ["karni_context"])
    assert calls.log == ["run", "probe:load"]


def test_a_failure_the_guard_does_not_explain_is_returned(host_project, monkeypatch) -> None:
    calls = _install(monkeypatch, Calls(None, returncode=1))
    assert run_manage(host_project, ["karni_context"]).returncode == 1
    assert calls.log == ["run", "probe:load"]


def test_run_manage_loads_and_run_python_does_not_check(host_project, monkeypatch) -> None:
    calls = _install(monkeypatch, Calls(None))
    run_manage(host_project, ["routes"], capture=False)
    run_python(host_project, ["-c", "import pytest"], capture=False)
    assert calls.log == ["probe:load", "run", "run"]


def test_the_escape_hatch_turns_the_guard_off(host_project, monkeypatch) -> None:
    calls = _install(monkeypatch, Calls(DRIVER))
    for value in ("false", "0", "no", "OFF"):
        monkeypatch.setenv(database.ENV, value)
        run_manage(host_project, ["migrate"], capture=False, database="connect")
    run_manage(host_project, ["migrate"], capture=False, database=None)
    monkeypatch.delenv(database.ENV)
    run_manage(host_project, ["migrate"], capture=False, database=None)
    assert calls.log == ["run"] * 6


def test_docker_runs_are_not_checked(tmp_path, monkeypatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: True)
    calls = _install(monkeypatch, Calls(DRIVER))
    run_manage(tmp_path, ["migrate"], capture=False, database="connect")
    assert calls.log == ["run"]


@pytest.mark.parametrize(
    ("argv", "use"),
    [
        (["migrate"], "connect"),
        (["seed"], "connect"),
        (["sync-roles"], "connect"),
        (["createsuperuser", "--noinput"], "connect"),
        (["manage", "showmigrations"], "connect"),
        (["serve", "--local"], "connect"),
        (["test"], "connect"),
        (["beat"], "connect"),
        (["worker"], "load"),
        (["shell"], "load"),
        (["routes"], "load"),
        (["schedule", "list"], "load"),
        (["make", "migration"], "load"),
    ],
)
def test_each_runner_declares_what_it_needs(argv, use, host_project, monkeypatch) -> None:
    monkeypatch.chdir(host_project)
    calls = _install(monkeypatch, Calls(None))
    result = CliRunner().invoke(app, argv)
    assert f"probe:{use}" in calls.log, (argv, calls.log, result.output)


def test_karni_check_reports_the_backend_and_still_runs_the_frontend(
    host_project, monkeypatch
) -> None:
    import karni_cli.commands.check as check_mod

    monkeypatch.chdir(host_project)
    _install(monkeypatch, Calls(DRIVER))
    frontend: list[Path] = []

    def duplication(project: Path) -> int:
        frontend.append(project)
        return 0

    monkeypatch.setattr(check_mod, "_frontend_duplication", duplication)
    result = CliRunner().invoke(app, ["check"])
    assert result.exit_code == 1
    assert "error: C012:" in result.output and "karni check: FAILED" in result.output
    assert frontend == [host_project.resolve()]


# what it says


def test_the_driver_error_names_the_interpreter_and_every_fix(tmp_path) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    message = str(database.error(DRIVER, tmp_path, python))
    assert message.startswith("C012: DATABASES['default'] in config.settings uses ")
    assert "Error loading psycopg2 or psycopg module" in message
    assert f'{python} -m pip install "psycopg[binary]"' in message
    assert "`karni serve -d`" in message and "--docker" in message
    assert "KARNI_DB_CHECK=false" in message
    assert message.endswith(f"See {docs_url('C012')}")


def test_the_unreachable_error_names_the_address_and_the_fix(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("DATABASE_URL=postgres://karni@127.0.0.1/karni\n")
    message = str(database.error(DOWN, tmp_path, Path("python")))
    assert message.startswith("C013: Cannot connect to DATABASES['default'] in config.settings")
    assert "database karni at 127.0.0.1:5432" in message
    assert "Connection refused. This command" in message  # one period, not two
    assert "`karni serve -d`" in message and "sqlite:///db.sqlite3" in message
    assert "There is no .env" not in message and "`db`" not in message


def test_without_env_the_unreachable_error_says_so(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    compose = database.Finding("unreachable", "default", "x", "no such host", host="db")
    message = str(database.error(compose, tmp_path, Path("python")))
    assert "There is no .env: `cp .env.example .env`, then set DATABASE_URL." in message
    assert "`db` is the compose service's host name" in message


def test_parse_reads_only_the_marker_line() -> None:
    line = db_probe.MARKER + json.dumps({"status": "driver", "alias": "x", "engine": "e"})
    assert database.parse(f"noise\n{line}\n") == database.Finding("driver", "x", "e", "")
    assert database.parse(db_probe.MARKER + '{"status": "ok"}') is None
    assert database.parse(db_probe.MARKER + '{"status": "unknown"}') is None
    assert database.parse(db_probe.MARKER + "{not json") is None
    assert database.parse("Traceback (most recent call last):\n") is None


# the real probe, in a subprocess, against small Django settings


def _settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, databases: str) -> None:
    (tmp_path / "probe_settings.py").write_text(f"SECRET_KEY = 'x'\nDATABASES = {databases}\n")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "probe_settings")


@pytest.mark.db_probe
def test_probe_finds_a_missing_postgresql_driver(tmp_path, monkeypatch) -> None:
    for name in ("psycopg", "psycopg2"):  # shadow whatever this interpreter has installed
        (tmp_path / f"{name}.py").write_text(HIDE_POSTGRES_DRIVERS)
    _settings(tmp_path, monkeypatch, "{'default': {'ENGINE': 'django.db.backends.postgresql'}}")
    finding = database.probe(tmp_path, Path(sys.executable), "load")
    assert finding == database.Finding(
        "driver",
        "default",
        "django.db.backends.postgresql",
        "Error loading psycopg2 or psycopg module",
    )


@pytest.mark.db_probe
def test_probe_connects_only_when_asked(tmp_path, monkeypatch) -> None:
    backend = tmp_path / "down_backend"
    backend.mkdir()
    (backend / "__init__.py").write_text("")
    (backend / "base.py").write_text(
        "from django.db.backends.sqlite3.base import DatabaseWrapper as SQLite\n\n\n"
        "class DatabaseWrapper(SQLite):\n"
        "    vendor = 'down'\n\n"
        "    def get_new_connection(self, conn_params):\n"
        "        raise self.Database.OperationalError('connection refused (server is down)')\n"
    )
    _settings(
        tmp_path,
        monkeypatch,
        "{'default': {'ENGINE': 'down_backend', 'NAME': 'karni', 'HOST': 'h', 'PORT': '1'}}",
    )
    python = Path(sys.executable)
    assert database.probe(tmp_path, python, "load") is None
    assert database.probe(tmp_path, python, "connect") == database.Finding(
        "unreachable",
        "default",
        "down_backend",
        "connection refused (server is down)",
        host="h",
        port="1",
        name="karni",
    )


@pytest.mark.db_probe
def test_probe_passes_sqlite_without_creating_the_file(tmp_path, monkeypatch) -> None:
    db = tmp_path / "db.sqlite3"
    _settings(
        tmp_path,
        monkeypatch,
        f"{{'default': {{'ENGINE': 'django.db.backends.sqlite3', 'NAME': {str(db)!r}}}}}",
    )
    assert database.probe(tmp_path, Path(sys.executable), "connect") is None
    assert not db.exists()


@pytest.mark.db_probe
def test_probe_leaves_broken_settings_to_the_command(tmp_path, monkeypatch) -> None:
    (tmp_path / "probe_settings.py").write_text("raise RuntimeError('broken settings')\n")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "probe_settings")
    assert database.probe(tmp_path, Path(sys.executable), "connect") is None
    assert database.probe(tmp_path, tmp_path / "no-such-python", "load") is None


# end to end: a real project, a real interpreter, no PostgreSQL driver


@pytest.fixture
def driverless_project(
    generated_project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    """`karni new` + a PostgreSQL DATABASE_URL, run by this interpreter with psycopg hidden."""
    for name in ("psycopg", "psycopg2"):
        (generated_project / f"{name}.py").write_text(HIDE_POSTGRES_DRIVERS)
    monkeypatch.setenv("DATABASE_URL", "postgres://karni:karni@127.0.0.1:59999/karni")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("STATIC_ROOT", str(tmp_path / "static"))
    monkeypatch.setattr(project_mod, "_running_interpreter", lambda: Path(sys.executable))
    monkeypatch.chdir(generated_project)
    return generated_project


@pytest.mark.db_probe
@pytest.mark.parametrize("argv", [["context"], ["check", "--no-frontend"]])
def test_no_traceback_without_a_driver(argv, driverless_project, capfd) -> None:
    result = CliRunner().invoke(app, argv)
    seen = result.output + "".join(capfd.readouterr())  # the child writes to the real fds
    assert result.exit_code == 1, seen
    assert "C012: DATABASES['default'] in config.settings" in seen
    assert 'pip install "psycopg[binary]"' in seen
    assert "Traceback" not in seen
