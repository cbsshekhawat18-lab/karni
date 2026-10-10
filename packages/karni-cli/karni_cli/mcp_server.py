"""``karni mcp`` — Karni's agent surface as MCP tools (stdio).

Tools: ``context`` (the ``karni context`` inventory), ``rules`` (the
conventions, one rule in full, or a procedure) and ``check`` (static
violations for one file). The tool functions are plain functions so they are
testable without a client; :func:`build_server` registers them on the
official MCP Python SDK server (``pip install 'karni-cli[mcp]'``): ``MCPServer``
in mcp 2.x, ``FastMCP`` in mcp 1.x.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from karni_cli import agent_data
from karni_cli.adapters import module_fragments
from karni_cli.commands.context import build_context_text
from karni_cli.commands.rules import check_text
from karni_cli.project import CliError, find_project
from karni_cli.rules_render import render_explain, render_procedure, render_rules

INSTRUCTIONS = (
    "Karni project tools. Call `context` and `rules` before any work and follow what they "
    "return; call `check` on every file you write."
)

_project_override: Path | None = None


def _project() -> Path | None:
    return _project_override or find_project()


def context_tool() -> str:
    """Live project inventory: apps, models, viewsets, UI components, hooks, pages, modules."""
    project = _project()
    if project is None:
        return "error: not inside a Karni project (no manage.py found)."
    try:
        return build_context_text(project)
    except CliError as exc:
        return f"error: {exc}"


def rules_tool(code: str = "", procedure: str = "") -> str:
    """Karni conventions. No arguments: every rule's code + summary. ``code``: one rule in
    full (why + fix). ``procedure``: steps for new-model, new-page, add-module or new-module."""
    project = _project()
    try:
        data = agent_data.load(project)
    except CliError as exc:
        return f"error: {exc}"
    if code:
        rule = data.rule(code)
        return render_explain(rule) if rule else f"error: no rule {code!r}"
    if procedure:
        found = data.procedure(procedure)
        return render_procedure(found) if found else f"error: no procedure {procedure!r}"
    return render_rules(data, module_fragments(project) if project else {})


def check_tool(path: str) -> str:
    """Static check of one file against Karni's rules; returns violations with fixes."""
    project = _project()
    target = Path(path)
    if not target.is_absolute() and project is not None:
        target = project / target
    try:
        text, _count = check_text([target], project)
    except CliError as exc:
        return f"error: {exc}"
    return text


TOOLS: dict[str, Any] = {"context": context_tool, "rules": rules_tool, "check": check_tool}


def _server_class() -> Any:
    try:
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        pass
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[attr-defined,unused-ignore]

        return FastMCP
    except ImportError:
        raise CliError(
            "karni mcp needs the MCP SDK: pip install 'karni-cli[mcp]'", code="C006"
        ) from None


def build_server(project: Path | None = None) -> Any:
    """The configured (not yet running) MCP server."""
    global _project_override
    _project_override = project
    server = _server_class()(name="karni", instructions=INSTRUCTIONS)
    for name, function in TOOLS.items():
        server.tool(name=name, description=function.__doc__)(function)
    return server
