"""``karni recipes`` (experimental): ready-made app specs a new app starts from.

    karni recipes list [--json]                   every recipe, and the blank start
    karni recipes list --match "<request>"        the best few for a one-line request
    karni recipes show NAME [--json]              one recipe and its karni.yaml (blank: the
                                                  blank start)

The recipes come from :mod:`karni_cli.recipes`: the ones built into
karni-cli and the ``karni.recipes`` entry points of its environment.
``--match`` ranks them by plain word overlap with the request, with no
language model. See docs/app-spec.md#recipes.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import typer

from karni_cli.project import find_project

if TYPE_CHECKING:
    from karni_cli.recipes import Loaded

recipes_app = typer.Typer(
    help=(
        "Recipes (experimental): ready-made karni.yaml files a new app starts from, matched to "
        "a one-line request (list, show)."
    ),
    no_args_is_help=True,
    add_completion=False,
)

_JSON_HELP = (
    "Print {version, request, threshold, recipes, blank, next, problems} "
    "(docs/assets/karni-recipes.schema.json)."
)


def _load() -> tuple[Loaded, str]:
    from karni_cli import recipes as recipes_mod

    loaded = recipes_mod.load()
    for problem in loaded.problems:
        sys.stderr.write(f"warning: C421: {problem}\n")
    return loaded, recipes_mod.app_name(find_project())


def _row(entry: dict[str, Any], width: int) -> str:
    score = f"  {entry['score']:>2}" if entry["score"] is not None else ""
    line = f"{entry['name']:<{width}}{score}  {entry['title']}: {entry['purpose']}"
    if entry["matched"]:
        line += f" (matched: {', '.join(entry['matched'])})"
    return line


def _blank_lines(data: dict[str, Any]) -> list[str]:
    return ["karni.yaml of the blank start:", *data["blank"]["spec"].rstrip("\n").splitlines()]


@recipes_app.command("list")
def list_(
    match: str | None = typer.Option(
        None,
        "--match",
        help="A one-line request: the best few recipes for it, with their scores (2 for each "
        "word of the request a use_when phrase has, 1 for each one only the purpose has).",
        show_default=False,
    ),
    as_json: bool = typer.Option(False, "--json", help=_JSON_HELP),
) -> None:
    """Experimental. Every recipe, or with --match the best few for a request, and the blank start.

    --match compares the words of the request with each recipe's use_when
    and purpose, after lowercasing, making plurals singular and leaving out
    words that name no app (a, the, app, with ...). A recipe scores 2 for each
    word one of its use_when phrases has and 1 for each word only its purpose
    has. The recipes that score 2 or more come back, best first, at most 3.
    When none does, start from the blank start: karni.yaml with the version
    and the app's name, nothing else.
    """
    from karni_cli.recipes import output

    loaded, name = _load()
    data = (
        output.matched(loaded, match, app_name=name)
        if match is not None
        else output.listing(loaded, app_name=name)
    )
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    entries = data["recipes"]
    width = max((len(entry["name"]) for entry in entries), default=0)
    if match is None:
        if entries:
            typer.echo("Recipes: ready-made karni.yaml files (karni recipes show NAME).")
            for entry in entries:
                typer.echo(_row(entry, width))
        else:
            typer.echo("No recipe is installed.")
        typer.echo(
            "blank: the blank start, karni.yaml with the version and the app's name "
            "(karni recipes show blank)."
        )
    elif entries:
        typer.echo(f'Recipes for "{match}", best first (score, then name):')
        for entry in entries:
            typer.echo(_row(entry, width))
    else:
        typer.echo(
            f'No recipe matches "{match}": none scores {data["threshold"]} or more. The blank '
            "start fits."
        )
        for line in _blank_lines(data):
            typer.echo(line)
    typer.echo(f"next: {data['next']}")


@recipes_app.command("show")
def show(
    name: str = typer.Argument(..., help="A recipe, or blank for the blank start."),
    as_json: bool = typer.Option(False, "--json", help=_JSON_HELP),
) -> None:
    """Experimental. One recipe: what it is for, what people usually change, its files and spec.

    blank shows the blank start: karni.yaml with the version and the app's
    name, nothing else, where an app starts when no recipe fits.
    """
    from karni_cli.recipes import output

    loaded, app = _load()
    data = output.shown(loaded, name, app_name=app)
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    if not data["recipes"]:
        typer.echo("blank: the blank start, where an app starts when no recipe fits.")
        for line in _blank_lines(data):
            typer.echo(line)
        typer.echo(f"next: {data['next']}")
        return
    entry = data["recipes"][0]
    lines = [
        f"{entry['name']}: {entry['title']} ({entry['source']})",
        entry["purpose"],
        "Use when: " + "; ".join(entry["use_when"]),
    ]
    if entry["usually_changed"]:
        lines.append("Usually changed: " + "; ".join(entry["usually_changed"]))
    if entry["files"]:
        lines.append("Files: " + ", ".join(entry["files"]))
    lines += ["karni.yaml:", *str(entry["spec"]).rstrip("\n").splitlines()]
    lines.append(f"next: {data['next']}")
    typer.echo("\n".join(lines))
