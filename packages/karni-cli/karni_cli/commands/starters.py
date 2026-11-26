"""``karni starters``: ready games a new game project starts from.

    karni starters list [--json]                  every starter, and the blank start
    karni starters list --match "<request>"       the best few for a one-line request
    karni starters show GENRE [--json]            one starter: what it is and the files it writes

The starters come from :mod:`karni_cli.starters`: the blank start built into
karni-cli and the ``karni.starters`` entry points of its environment
(karni-game ships the runner). ``--match`` ranks them by the recipes' plain
word overlap, with no language model. ``karni new "<Name>" --kind game
--genre <genre>`` writes one. See docs/game-starters.md.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import typer

from karni_cli import starters as starters_mod

starters_app = typer.Typer(
    help=(
        "Game starters: ready games karni new --kind game --genre <genre> "
        "writes, matched to a one-line request (list, show)."
    ),
    no_args_is_help=True,
    add_completion=False,
)

#: The version of the --json output. It moves only for a breaking change.
STARTERS_VERSION = 1


def _load() -> starters_mod.Loaded:
    loaded = starters_mod.load()
    for problem in loaded.problems:
        sys.stderr.write(f"warning: {problem}\n")
    return loaded


def _entry(
    starter: starters_mod.Starter, score: int | None = None, matched: tuple[str, ...] = ()
) -> dict[str, Any]:
    return {
        "name": starter.name,
        "title": starter.title,
        "purpose": starter.purpose,
        "use_when": list(starter.use_when),
        "usually_changed": list(starter.usually_changed),
        "source": starter.source,
        "score": score,
        "matched": list(matched),
        "new": f'karni new "{starter.example or "My Game"}" --kind game --genre {starter.name}',
    }


def _missing(loaded: starters_mod.Loaded) -> list[str]:
    return [
        f"{genre}: comes with {package} (pip install {package})"
        for genre, package in sorted(starters_mod.PACKAGES.items())
        if genre not in loaded.starters
    ]


@starters_app.command("list")
def list_(
    match: str | None = typer.Option(
        None,
        "--match",
        help="A one-line request: the best few starters for it, with their scores (as karni "
        "recipes list --match scores recipes).",
        show_default=False,
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Print {version, request, starters, blank, missing, problems}."
    ),
) -> None:
    """Every starter, or with --match the best few for a request, and the blank start."""
    loaded = _load()
    if match is None:
        entries = [
            _entry(s) for name, s in sorted(loaded.starters.items()) if name != starters_mod.BLANK
        ]
    else:
        entries = [
            _entry(m.starter, m.score, m.matched)
            for m in starters_mod.match(loaded.starters.values(), match)
        ]
    if as_json:
        data = {
            "version": STARTERS_VERSION,
            "request": match,
            "starters": entries,
            "blank": _entry(starters_mod.BLANK_STARTER),
            "missing": _missing(loaded),
            "problems": loaded.problems,
        }
        typer.echo(json.dumps(data, indent=2))
        return
    width = max((len(e["name"]) for e in entries), default=5)
    if match is not None:
        typer.echo(
            f'Starters for "{match}", best first (score, then name):'
            if entries
            else f'No starter fits "{match}": start from blank.'
        )
    else:
        typer.echo(
            "Starters: ready games for karni new --kind game --genre <genre> (karni starters show <genre>)."
        )
    for entry in entries:
        score = f"  {entry['score']:>2}" if entry["score"] is not None else ""
        line = f"{entry['name']:<{width}}{score}  {entry['title']}: {entry['purpose']}"
        if entry["matched"]:
            line += f" (matched: {', '.join(entry['matched'])})"
        typer.echo(line)
    typer.echo(
        f"{starters_mod.BLANK:<{width}}  {starters_mod.BLANK_STARTER.purpose} (--genre blank, the default)"
    )
    for line in _missing(loaded):
        typer.echo(f"  not installed: {line}")


@starters_app.command("show")
def show(
    genre: str = typer.Argument(..., help="A starter's name (karni starters list), or blank."),
    as_json: bool = typer.Option(False, "--json", help="Print the starter and its files as JSON."),
) -> None:
    """One starter: what it is, what people usually change, and the files it writes."""
    loaded = _load()
    starter = loaded.require(genre)
    data = _entry(starter)
    data["files"] = {"game": starter.game_files(), "project": starter.project_files()}
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    typer.echo(f"{starter.name}: {starter.title}. {starter.purpose}.")
    typer.echo(f"source: {starter.source}")
    if starter.use_when:
        typer.echo(f"use when: {', '.join(starter.use_when)}")
    for changed in starter.usually_changed:
        typer.echo(f"usually changed: {changed}")
    if starter.name == starters_mod.BLANK:
        typer.echo("files: the game of karni new --kind game (docs/apps-and-games.md)")
    else:
        typer.echo("files in game/<slug>/: " + ", ".join(starter.game_files()))
        typer.echo("files of the project: " + ", ".join(starter.project_files()))
    typer.echo(f"start: {data['new']}")
