"""``karni why`` / ``karni why-empty``: the question's shape, the manage.py call, the MCP tools.

The decision itself is computed in the project (``manage.py karni_why``,
tested in packages/karni/tests/why); here the subprocess layer is mocked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli import mcp_server
from karni_cli import project as project_mod
from karni_cli.commands.why import why_args, why_empty_args
from karni_cli.main import app
from karni_cli.project import CliError


class Recorder:
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
    monkeypatch.setenv("KARNI_DB_CHECK", "false")
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_mcp_project() -> Any:
    yield
    mcp_server._project_override = None


def test_the_forms_become_manage_py_arguments() -> None:
    assert why_args("events/42", user="a@x.test") == ["karni_why", "events/42", "--as", "a@x.test"]
    assert why_args("403", "abc") == ["karni_why", "403", "abc"]
    assert why_args(
        "events/42",
        user="a@x.test",
        action="update",
        method="patch",
        params=["status=draft"],
        as_json=True,
    ) == [
        "karni_why",
        "events/42",
        "--as",
        "a@x.test",
        "--action",
        "update",
        "--method",
        "patch",
        "--param",
        "status=draft",
        "--json",
    ]
    assert why_empty_args("events/", user="anonymous") == [
        "karni_why",
        "events",
        "--empty",
        "--as",
        "anonymous",
    ]


@pytest.mark.parametrize(
    ("call", "code"),
    [
        (lambda: why_args("403"), "C310"),
        (lambda: why_args("events/1", "abc", user="a"), "C310"),
        (lambda: why_args("events/", user="a"), "C310"),
        (lambda: why_args(" "), "C310"),
        (lambda: why_args("events/1"), "C311"),
        (lambda: why_empty_args("events", user=None), "C311"),
        (lambda: why_empty_args("", user="a"), "C310"),
    ],
)
def test_a_malformed_question_is_a_coded_error(call: Any, code: str) -> None:
    with pytest.raises(CliError) as caught:
        call()
    assert caught.value.code == code
    assert "karni why" in caught.value.message


def test_karni_why_runs_the_project_command(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder(stdout="user     a@x.test\nresult   404 Not Found\n")
    monkeypatch.setattr(project_mod, "run_process", recorder)
    result = CliRunner().invoke(app, ["why", "events/42", "--as", "a@x.test", "--action", "delete"])
    assert result.exit_code == 0, result.output
    assert "result   404 Not Found" in result.output
    (call,) = recorder.calls
    assert call["cmd"][-7:] == [
        "manage.py",
        "karni_why",
        "events/42",
        "--as",
        "a@x.test",
        "--action",
        "delete",
    ]
    assert call["capture"] is True and call["cwd"] == project


def test_karni_why_empty_and_its_exit_code(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder(returncode=1, stderr="CommandError: E901: No API resource named 'x'.")
    monkeypatch.setattr(project_mod, "run_process", recorder)
    result = CliRunner().invoke(app, ["why-empty", "x", "--as", "a@x.test", "--param", "k=v"])
    assert result.exit_code == 1
    assert recorder.calls[0]["cmd"][-7:] == [
        "karni_why",
        "x",
        "--empty",
        "--as",
        "a@x.test",
        "--param",
        "k=v",
    ]


def test_an_old_project_karni_is_c312(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder(returncode=1, stderr="Unknown command: 'karni_why'\nType 'manage.py help'")
    monkeypatch.setattr(project_mod, "run_process", recorder)
    result = CliRunner().invoke(app, ["why", "events/1", "--as", "a"])
    assert result.exit_code != 0
    assert isinstance(result.exception, CliError) and result.exception.code == "C312"


def test_the_mcp_tools_ask_the_same_question(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = Recorder(stdout="result   403 Forbidden\n")
    monkeypatch.setattr(project_mod, "run_process", recorder)
    assert mcp_server.why_tool("events/7", user="a@x.test", action="update") == (
        "result   403 Forbidden"
    )
    assert recorder.calls[-1]["cmd"][-6:] == [
        "karni_why",
        "events/7",
        "--as",
        "a@x.test",
        "--action",
        "update",
    ]
    mcp_server.why_tool("403 req-1")
    assert recorder.calls[-1]["cmd"][-3:] == ["karni_why", "403", "req-1"]
    mcp_server.why_empty_tool("events", "a@x.test", params="status=draft&page=2", as_json=True)
    assert recorder.calls[-1]["cmd"][-10:] == [
        "karni_why",
        "events",
        "--empty",
        "--as",
        "a@x.test",
        "--param",
        "status=draft",
        "--param",
        "page=2",
        "--json",
    ]
    assert mcp_server.why_tool("events/7").startswith("error: C311")


def test_the_mcp_tools_report_errors_as_text(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        project_mod, "run_process", Recorder(returncode=1, stderr="CommandError: E902: No user")
    )
    assert mcp_server.why_tool("events/7", user="who") == "error: CommandError: E902: No user"


def test_the_tools_need_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert mcp_server.why_empty_tool("events", "a").startswith("error: not inside a Karni project")
