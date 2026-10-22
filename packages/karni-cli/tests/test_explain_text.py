"""``karni explain -`` and ``karni queries`` in the CLI, and their MCP tools.

The catalogue itself is tested in packages/karni (tests/debugging); here: it
loads by path without Django, reads stdin, adds the CLI's own codes and the
agent rules, and ``karni queries`` hands its arguments to the project.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli import errorcodes, mcp_server
from karni_cli import project as project_mod
from karni_cli.commands import queries as queries_mod
from karni_cli.main import app
from karni_cli.project import CliError

from .conftest import REPO_ROOT

FIXTURES = REPO_ROOT / "packages" / "karni" / "tests" / "debugging" / "fixtures"
runner = CliRunner()


def _fixture(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _outside_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)
    yield
    mcp_server._project_override = None


def test_the_catalogue_loads_by_path_without_django() -> None:
    module = errorcodes.failures_module()
    assert module is not None
    assert module.__name__ == "karni_cli._bundled_karni_errorcodes.failures"
    assert "django" not in {name.split(".")[0] for name in module.__dict__}


def test_explain_reads_stdin() -> None:
    result = runner.invoke(app, ["explain", "-"], input=_fixture("e104_owned_path"))
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Class: E104  Owned() does not name a path to the user")
    assert "Cause: EventViewSet: Owned('organiser')" in result.output
    assert "Docs:  https://" in result.output


def test_explain_reads_stdin_without_a_dash() -> None:
    result = runner.invoke(app, ["explain"], input=_fixture("db_refused"))
    assert result.exit_code == 0, result.output
    assert "Class: C013  The database cannot be reached" in result.output


def test_cli_codes_are_registered_entries() -> None:
    """With the CLI's registry, C012 text gets the registered entry (title, why, fix)."""
    result = runner.invoke(app, ["explain", "-"], input=_fixture("cli_c012"))
    assert "Class: C012  The project's database driver is not installed" in result.output
    assert "Why:" in result.output and "errors/#c012" in result.output


def test_architecture_violations_map_to_agent_rules() -> None:
    result = runner.invoke(app, ["explain", "-"], input=_fixture("karni_check_model_base"))
    assert result.output.startswith("Class: K101  Agent rule K101")
    assert "Class: E702" in result.output  # the summary code comes last


def test_explain_json_for_agents() -> None:
    result = runner.invoke(app, ["explain", "-", "--json"], input=_fixture("pytest_e117"))
    data = json.loads(result.output)
    assert data["recognised"] is True
    assert data["findings"][0]["next"] == "karni queries EventViewSet.list --as <user>"


def test_an_inline_log_line_is_explained() -> None:
    result = runner.invoke(app, ["explain", "OperationalError: no such table: shop_order"])
    assert result.exit_code == 0
    assert "shop_order" in result.output and "karni migrate" in result.output


def test_unknown_text_is_said_plainly() -> None:
    result = runner.invoke(app, ["explain", "-"], input=_fixture("unknown_zero_division"))
    assert result.exit_code == 0
    assert result.output.startswith("Not a failure Karni recognises: ZeroDivisionError")


def test_nothing_to_explain() -> None:
    result = runner.invoke(app, ["explain", "-"], input="")
    assert isinstance(result.exception, CliError) and result.exception.code == "C340"


def test_explain_codes_still_work() -> None:
    result = runner.invoke(app, ["explain", "C340"])
    assert result.exit_code == 0 and result.output.startswith("C340  Nothing to explain")


def test_explain_dash_in_a_real_process() -> None:
    """The console script, stdin piped: what an agent runs."""
    proc = subprocess.run(
        [sys.executable, "-m", "karni_cli.main", "explain", "-"],
        input=_fixture("csrf_token_missing"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Class: CSRF check failed (session mode)" in proc.stdout


# karni queries


def test_queries_passes_its_arguments_to_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "manage.py").write_text("")
    calls: list[list[str]] = []

    def run_manage(project: Path, args: list[str], **kwargs: object) -> object:
        calls.append(args)
        assert kwargs["database"] == "connect"
        return subprocess.CompletedProcess(args, 0, stdout="28 queries — …\n", stderr="")

    monkeypatch.setattr(project_mod, "run_manage", run_manage)
    result = runner.invoke(
        app,
        [
            "queries",
            "events/1",
            "--as",
            "ann@example.com",
            "--method",
            "PATCH",
            "--data",
            "{}",
            "--json",
            "--explain",
            "--all",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "karni_queries",
            "events/1",
            "--method",
            "PATCH",
            "--as",
            "ann@example.com",
            "--data",
            "{}",
            "--json",
            "--explain",
            "--all",
        ]
    ]
    assert result.output == "28 queries — …\n"


def test_queries_exit_code_and_stderr_pass_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 1, stdout="", stderr="E940: nowhere\n"),
    )
    result = runner.invoke(app, ["queries", "nowhere"])
    assert result.exit_code == 1


def test_queries_on_an_old_karni(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "manage.py").write_text("")
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 1, stdout="", stderr="Unknown command: 'karni_queries'\n"
        ),
    )
    result = runner.invoke(app, ["queries", "events"])
    assert isinstance(result.exception, CliError) and result.exception.code == "C341"


def test_queries_outside_a_project() -> None:
    result = runner.invoke(app, ["queries", "events"])
    assert isinstance(result.exception, CliError) and result.exception.code == "C001"


# MCP tools


def test_explain_text_tool() -> None:
    assert mcp_server.explain_text_tool(_fixture("api_404")).startswith("Class: 404 from a Karni")
    assert mcp_server.explain_text_tool("").startswith("error: C340")


def test_queries_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert mcp_server.queries_tool("events").startswith("error: not inside a Karni project")
    (tmp_path / "manage.py").write_text("")
    seen: list[list[str]] = []

    def run_manage(project: Path, args: list[str], **kwargs: object) -> object:
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="report\n", stderr="")

    monkeypatch.setattr(project_mod, "run_manage", run_manage)
    assert mcp_server.queries_tool("events", as_user="ann", explain=True) == "report"
    assert seen == [["karni_queries", "events", "--method", "GET", "--as", "ann", "--explain"]]
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 1, stdout="", stderr="E941: who?\n"),
    )
    assert mcp_server.queries_tool("events", as_user="x") == "error: E941: who?"


def test_queries_args_shape() -> None:
    assert queries_mod.queries_args("events", None, "GET", None, False, False, False) == [
        "karni_queries",
        "events",
        "--method",
        "GET",
    ]
