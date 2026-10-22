"""Entry point for the ``karni`` command."""

from __future__ import annotations

import typer

from karni_cli import __version__
from karni_cli.commands.add import add
from karni_cli.commands.beat import beat
from karni_cli.commands.check import check
from karni_cli.commands.config import config_app
from karni_cli.commands.context import context
from karni_cli.commands.createsuperuser import createsuperuser
from karni_cli.commands.doctor import doctor
from karni_cli.commands.explain import explain
from karni_cli.commands.make import make_app, register_aliases
from karni_cli.commands.manage_passthrough import manage
from karni_cli.commands.mcp import mcp
from karni_cli.commands.migrate import migrate
from karni_cli.commands.new import new
from karni_cli.commands.queries import queries
from karni_cli.commands.routes import routes
from karni_cli.commands.rules import rules_app
from karni_cli.commands.run_tests import test
from karni_cli.commands.schedule import schedule_app
from karni_cli.commands.seed import seed
from karni_cli.commands.serve import serve
from karni_cli.commands.shell import shell
from karni_cli.commands.sync_roles import sync_roles
from karni_cli.commands.types import types
from karni_cli.commands.upgrade import upgrade
from karni_cli.commands.worker import worker
from karni_cli.project import PASSTHROUGH, CliError

app = typer.Typer(
    name="karni",
    help="The Karni framework CLI.",
    no_args_is_help=True,
    add_completion=False,
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"karni-cli {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_show_version,
        is_eager=True,
        help="Print the karni-cli version and exit (the project's karni: karni doctor).",
    ),
) -> None:
    """The Karni framework CLI."""


app.command(help="Scaffold a project from templates/project")(new)
app.command(help="Install an optional module and wire it into settings")(add)
app.command(help="Generate TS types and typed hooks from the backend OpenAPI")(types)
app.command(help="Print a compact machine-readable project inventory")(context)
app.command(help="Run architecture and system checks")(check)
app.command(help="Upgrade across Karni versions: codemods, diff, manual-change report")(upgrade)
app.add_typer(rules_app, name="rules")
app.command(
    help="Serve context, rules, check, explain_text and queries as MCP tools (needs karni-cli[mcp])"
)(mcp)
app.command(help="Report the environment: project, interpreter, Node, adapters, history")(doctor)
app.command(
    help="Explain an error code (E104, C101, PAY004, K106), or a pasted traceback or log "
    "line (karni explain -): class, cause, where, fix"
)(explain)
app.add_typer(config_app, name="config")

# Runners: each wraps one project command (named in its --help), run through
# the project interpreter (.venv, else the running compose service).
app.command()(serve)
app.command(context_settings=PASSTHROUGH)(migrate)
app.command(context_settings=PASSTHROUGH)(test)
app.command(context_settings=PASSTHROUGH)(shell)
app.command()(routes)
app.command()(queries)
app.command(context_settings=PASSTHROUGH)(worker)
app.command(context_settings=PASSTHROUGH)(beat)
app.add_typer(schedule_app, name="schedule")
app.command(context_settings=PASSTHROUGH)(seed)
app.command("sync-roles", context_settings=PASSTHROUGH)(sync_roles)
app.command(context_settings=PASSTHROUGH)(createsuperuser)
app.command(context_settings=PASSTHROUGH)(manage)

# Generators: `karni make <type>` (+ hidden `karni make:<type>` aliases).
app.add_typer(make_app, name="make")
register_aliases(app)


def run() -> None:
    """Console-script entry that renders CliError without a traceback."""
    try:
        app(standalone_mode=True)
    except CliError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
