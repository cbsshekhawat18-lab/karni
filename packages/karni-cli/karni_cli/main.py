"""Entry point for the ``karni`` command."""

from __future__ import annotations

import typer

from karni_cli.commands.add import add
from karni_cli.commands.check import check
from karni_cli.commands.context import context
from karni_cli.commands.mcp import mcp
from karni_cli.commands.new import new
from karni_cli.commands.rules import rules_app
from karni_cli.commands.types import types
from karni_cli.commands.upgrade import upgrade
from karni_cli.project import CliError

app = typer.Typer(
    name="karni",
    help="The Karni framework CLI.",
    no_args_is_help=True,
    add_completion=False,
)

app.command(help="Scaffold a project from templates/project")(new)
app.command(help="Install an optional module and wire it into settings")(add)
app.command(help="Generate TS types and typed hooks from the backend OpenAPI")(types)
app.command(help="Print a compact machine-readable project inventory")(context)
app.command(help="Run architecture and system checks")(check)
app.command(help="Apply mechanical migrations between Karni versions")(upgrade)
app.add_typer(rules_app, name="rules")
app.command(help="Serve context, rules and check as MCP tools (needs karni-cli[mcp])")(mcp)


def run() -> None:
    """Console-script entry that renders CliError without a traceback."""
    try:
        app(standalone_mode=True)
    except CliError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
