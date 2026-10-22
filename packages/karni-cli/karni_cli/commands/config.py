"""``karni config`` — read and write Karni CLI settings.

karni config list                       every setting, its value and where it comes from
karni config get suggest_tools          the effective value (project > global > default)
karni config set suggest_tools false    write it to .karni/config.toml (committed)
karni config set --global KEY VALUE     write it to ~/.config/karni/config.toml
"""

from __future__ import annotations

from pathlib import Path

import typer

from karni_cli import config as config_mod
from karni_cli.project import CliError, find_project

config_app = typer.Typer(
    help=(
        "Read and write Karni settings in the project's .karni/config.toml (committed) "
        "or, with --global, in ~/.config/karni/config.toml. The project's value wins."
    ),
    no_args_is_help=True,
    add_completion=False,
)

_GLOBAL_HELP = "Use the global file ($XDG_CONFIG_HOME/karni/config.toml) only."


def _source(value: config_mod.Value, project: Path | None) -> str:
    if value.path is None:
        return value.source
    shown: Path = value.path
    if project is not None:
        try:
            shown = value.path.relative_to(project)
        except ValueError:
            pass
    return f"{value.source}: {shown}"


@config_app.command("get")
def get_command(
    key: str = typer.Argument(..., help="Setting name (see `karni config list`)."),
    global_: bool = typer.Option(False, "--global", help=_GLOBAL_HELP),
) -> None:
    """Print the effective value of KEY."""
    value = config_mod.resolve(key, find_project(), global_only=global_)
    typer.echo(config_mod.render(value.value))


@config_app.command("set")
def set_command(
    key: str = typer.Argument(..., help="Setting name (see `karni config list`)."),
    value: str = typer.Argument(..., help="New value (true/false)."),
    global_: bool = typer.Option(False, "--global", help=_GLOBAL_HELP),
) -> None:
    """Set KEY to VALUE in the project file (or --global)."""
    parsed = config_mod.parse(key, value)
    if global_:
        path = config_mod.global_path()
    else:
        project = find_project()
        if project is None:
            raise CliError(
                "Not inside a Karni project (no manage.py here or above) — "
                "use --global to set it for every project.",
                code="C001",
            )
        path = config_mod.project_path(project)
    config_mod.write(key, parsed, path)
    typer.echo(f"{key} = {config_mod.render(parsed)} ({path})")


@config_app.command("list")
def list_command() -> None:
    """Every setting with its effective value and source."""
    project = find_project()
    for name in sorted(config_mod.KEYS):
        value = config_mod.resolve(name, project)
        typer.echo(f"{name} = {config_mod.render(value.value)}  # {_source(value, project)}")
