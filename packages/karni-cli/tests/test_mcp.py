"""`karni mcp`: the tool functions directly, plus a server-construction smoke test."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from karni_cli import mcp_server
from karni_cli import project as project_mod

from .conftest import REPO_ROOT

FIXTURES = REPO_ROOT / "packages" / "karni" / "tests" / "agent" / "fixtures"


@pytest.fixture(autouse=True)
def _reset_project_override():
    yield
    mcp_server._project_override = None


def test_rules_tool(generated_project: Path, monkeypatch) -> None:
    monkeypatch.chdir(generated_project)
    listing = mcp_server.rules_tool()
    assert "K101!" in listing and "K204!" in listing
    assert "Why:" in mcp_server.rules_tool(code="K202")
    assert "1. Run `karni context`" in mcp_server.rules_tool(procedure="new-page")
    assert mcp_server.rules_tool(code="K999").startswith("error:")


def test_check_tool(monkeypatch) -> None:
    monkeypatch.chdir(FIXTURES)
    bad = mcp_server.check_tool("app/bad_models.py")
    assert "K101" in bad and "fix:" in bad
    assert mcp_server.check_tool("frontend/src/pages/good_page.tsx").startswith("ok:")
    assert mcp_server.check_tool("missing.py").startswith("error:")


def test_context_tool(generated_project: Path, monkeypatch) -> None:
    monkeypatch.chdir(generated_project)
    backend = "MODELS: Event(title)\nBASES: BaseModel BaseViewSet"
    monkeypatch.setattr(
        project_mod,
        "run_manage",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=backend, stderr=""),
    )
    # The scaffold ships one page (frontend/src/pages/home.tsx), read statically.
    expected = "MODELS: Event(title)\nPAGES: home\nBASES: BaseModel BaseViewSet"
    assert mcp_server.context_tool() == expected


def test_context_tool_outside_a_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert mcp_server.context_tool().startswith("error:")


def test_server_registers_the_tools(generated_project: Path) -> None:
    pytest.importorskip("mcp")
    server = mcp_server.build_server(generated_project)
    tools = asyncio.run(server.list_tools())
    assert sorted(tool.name for tool in tools) == [
        "check",
        "context",
        "explain_text",
        "queries",
        "rules",
    ]
    schemas = {
        # mcp 2.x: input_schema; mcp 1.x: inputSchema
        tool.name: getattr(tool, "input_schema", None) or tool.inputSchema
        for tool in tools
    }
    assert "path" in schemas["check"]["properties"]
    assert set(schemas["rules"]["properties"]) == {"code", "procedure"}
    assert set(schemas["explain_text"]["properties"]) == {"text"}
    assert set(schemas["queries"]["properties"]) == {
        "endpoint",
        "as_user",
        "method",
        "data",
        "explain",
    }
    # The --project root is what the tools use, wherever the server was started.
    assert mcp_server._project() == generated_project
