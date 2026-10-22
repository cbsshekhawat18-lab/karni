"""``karni make <type>`` — artisan-style generators (and the ``make:<type>`` aliases).

Every generator writes project code only, never overwrites without
``--force``, previews with ``--dry-run``, prints each created/modified file,
and edits existing files only through marker comments or AST-located
appends. ``karni make --list`` prints them all; the generators themselves
live in :mod:`karni_cli.generators`.
"""

from __future__ import annotations

import typer

from karni_cli.generators import GENERATORS

make_app = typer.Typer(
    help=(
        "Generate project code: apps, models, viewsets, tasks, schedules, listeners, pages "
        "... (`karni make --list`). It never overwrites without --force, and --dry-run previews."
    ),
    no_args_is_help=False,
    add_completion=False,
)


def list_text() -> str:
    width = max(len(g.name) for g in GENERATORS) + 2
    return "\n".join(f"{g.name:<{width}}{g.summary}" for g in GENERATORS)


@make_app.callback(invoke_without_command=True)
def make(
    ctx: typer.Context,
    list_: bool = typer.Option(
        False, "--list", help="Print every generator with a one-line summary."
    ),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if list_:
        typer.echo(list_text())
        return
    typer.echo(ctx.get_help())


for _generator in GENERATORS:
    make_app.command(_generator.name, short_help=_generator.summary)(_generator.command)


def register_aliases(app: typer.Typer) -> None:
    """``karni make:<type>`` — hidden Laravel-style aliases for every generator."""
    for generator in GENERATORS:
        app.command(f"make:{generator.name}", hidden=True, short_help=generator.summary)(
            generator.command
        )
