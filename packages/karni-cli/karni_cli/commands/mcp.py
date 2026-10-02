"""``karni mcp`` — run the Karni MCP server on stdio (``pip install 'karni-cli[mcp]'``)."""

from __future__ import annotations

from pathlib import Path

import typer

from karni_cli.project import find_project


def mcp(
    project: Path | None = typer.Option(
        None, "--project", help="Project root (default: found from the working directory)."
    ),
) -> None:
    from karni_cli.mcp_server import build_server  # lazy: the MCP SDK is an extra

    root = project.resolve() if project is not None else find_project()
    build_server(root).run()
