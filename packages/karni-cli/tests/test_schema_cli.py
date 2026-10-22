"""``karni schema``: runs ``manage.py karni_schema`` in the project and names an old karni."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli import project as project_mod
from karni_cli.main import app
from karni_cli.project import CliError


class _Run:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = (returncode, stdout, stderr)

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"cmd": cmd, **kwargs})
        code, out, err = self.result
        return subprocess.CompletedProcess(cmd, code, stdout=out, stderr=err)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "manage.py").write_text("")
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda p, s: False)
    return tmp_path


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], ["karni_schema", "--database", "default"]),
        (
            ["events", "shop.Order", "--json"],
            ["karni_schema", "events", "shop.Order", "--json", "--database", "default"],
        ),
        (
            ["--no-db", "--database", "replica"],
            ["karni_schema", "--no-db", "--database", "replica"],
        ),
    ],
)
def test_schema_runs_the_management_command(
    project: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str], expected: list[str]
) -> None:
    run = _Run(stdout="events.Event  (table events_event, postgresql)\n")
    monkeypatch.setattr(project_mod, "run_process", run)
    result = CliRunner().invoke(app, ["schema", *argv])
    assert result.exit_code == 0, result.output
    (call,) = run.calls
    assert call["cmd"] == [str(project / ".venv" / "bin" / "python"), "manage.py", *expected]
    assert "events.Event  (table events_event" in result.output


def test_an_old_karni_gets_a_coded_upgrade_hint(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Run(returncode=1, stderr="Unknown command: 'karni_schema'\n")
    monkeypatch.setattr(project_mod, "run_process", run)
    result = CliRunner().invoke(app, ["schema"])
    assert isinstance(result.exception, CliError)
    assert result.exception.code == "C361"


def test_a_failure_keeps_its_exit_code(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_mod, "run_process", _Run(returncode=1, stderr="E969: nope\n"))
    result = CliRunner().invoke(app, ["schema", "nope"])
    assert result.exit_code == 1


def test_help_states_what_it_wraps() -> None:
    result = CliRunner().invoke(app, ["schema", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0 and "manage.py karni_schema" in result.output
