"""`karni trace`, `karni replay`, `karni explain --failure` and their MCP tools.

The project side (``manage.py karni_trace`` ...) is tested in packages/karni
(tests/test_debug.py); here the subprocess layer is mocked and the tests
assert the argv each command runs and how output and errors come back.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli import mcp_server
from karni_cli import project as project_mod
from karni_cli.main import app

runner = CliRunner()


class Manage:
    """Stands in for ``project.run_manage``; records argv, answers with fixed output."""

    def __init__(self, stdout: str = "ok", stderr: str = "", returncode: int = 0) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = (stdout, stderr, returncode)

    def __call__(self, project: Path, args: list[str], **kwargs: Any) -> Any:
        self.calls.append({"args": args, **kwargs})
        stdout, stderr, code = self.result
        return subprocess.CompletedProcess(args, code, stdout=stdout, stderr=stderr)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def manage(monkeypatch: pytest.MonkeyPatch) -> Manage:
    fake = Manage(stdout="Request abc: GET /api/x/ -> 200\n")
    monkeypatch.setattr(project_mod, "run_manage", fake)
    return fake


def test_trace_runs_karni_trace_and_prints_its_output(project: Path, manage: Manage) -> None:
    result = runner.invoke(app, ["trace", "last", "--json"])
    assert result.exit_code == 0, result.output
    assert manage.calls[0]["args"] == ["karni_trace", "last", "--json"]
    assert manage.calls[0]["capture"] is True and manage.calls[0]["database"] == "load"
    assert "Request abc" in result.output


def test_replay_passes_every_option(project: Path, manage: Manage) -> None:
    result = runner.invoke(
        app,
        [
            "replay",
            "abc",
            "--as",
            "ops@example.com",
            "--set",
            "password=s3cret",
            "--set",
            "query:token=t",
            "--drop-redacted",
            "--commit",
        ],
    )
    assert result.exit_code == 0, result.output
    assert manage.calls[0]["args"] == [
        "karni_replay",
        "abc",
        "--as",
        "ops@example.com",
        "--set",
        "password=s3cret",
        "--set",
        "query:token=t",
        "--drop-redacted",
        "--commit",
    ]
    assert manage.calls[0]["database"] == "connect"


def test_replay_rejects_a_malformed_set(project: Path, manage: Manage) -> None:
    result = runner.invoke(app, ["replay", "abc", "--set", "password"])
    assert result.exit_code != 0
    assert "C321" in str(result.exception) and not manage.calls


def test_explain_failure_runs_karni_failure(project: Path, manage: Manage) -> None:
    result = runner.invoke(app, ["explain", "--failure", "last"])
    assert result.exit_code == 0, result.output
    assert manage.calls[0]["args"] == ["karni_failure", "last"]


def test_explain_still_explains_codes_without_a_project(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["explain", "E921"])
    assert result.exit_code == 0, result.output
    assert "Nothing was captured for this request id" in result.output


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["explain"], "C340"),  # nothing given: nothing to explain (an empty stdin)
        (["explain", "E104", "--failure", "last"], "C320"),  # a code and --failure at once
    ],
)
def test_explain_needs_exactly_one_thing(
    project: Path, manage: Manage, argv: list[str], code: str
) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code != 0
    assert code in str(result.exception) and not manage.calls


def test_a_coded_project_error_keeps_its_code(project: Path, monkeypatch: Any) -> None:
    stderr = (
        "KarniCommandError: E921: Nothing was captured for request abc. Capture runs only with "
        "DEBUG on. See https://example.org/errors/#e921\n"
    )
    monkeypatch.setattr(project_mod, "run_manage", Manage(stdout="", stderr=stderr, returncode=1))
    result = runner.invoke(app, ["trace", "abc"])
    assert result.exit_code != 0
    error = result.exception
    assert getattr(error, "code", None) == "E921"
    assert str(error).startswith("E921: Nothing was captured for request abc.")


def test_an_old_karni_in_the_project_is_named(project: Path, monkeypatch: Any) -> None:
    stderr = "Unknown command: 'karni_trace'\nType 'manage.py help' for usage.\n"
    monkeypatch.setattr(project_mod, "run_manage", Manage(stdout="", stderr=stderr, returncode=1))
    result = runner.invoke(app, ["trace", "abc"])
    assert getattr(result.exception, "code", None) == "C322"


def test_an_uncoded_failure_is_c323(project: Path, monkeypatch: Any) -> None:
    stderr = "Traceback ...\nModuleNotFoundError: No module named 'shop'\n"
    monkeypatch.setattr(project_mod, "run_manage", Manage(stdout="", stderr=stderr, returncode=1))
    result = runner.invoke(app, ["replay", "abc"])
    assert getattr(result.exception, "code", None) == "C323"
    assert "No module named 'shop'" in str(result.exception)


# --- MCP ---------------------------------------------------------------------------


def test_mcp_debugging_tools(project: Path, manage: Manage) -> None:
    assert mcp_server.trace_tool("abc").startswith("Request abc")
    assert manage.calls[-1]["args"] == ["karni_trace", "abc"]
    mcp_server.replay_tool("abc", as_user="ops@example.com", sets=["password=x"])
    assert manage.calls[-1]["args"] == [
        "karni_replay",
        "abc",
        "--as",
        "ops@example.com",
        "--set",
        "password=x",
    ]
    mcp_server.explain_failure_tool()
    assert manage.calls[-1]["args"] == ["karni_failure", "last"]
    assert mcp_server.replay_tool("abc", sets=["oops"]).startswith("error: C321")


def test_mcp_debugging_tools_outside_a_project(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mcp_server, "_project_override", None)
    assert mcp_server.trace_tool().startswith("error:")
