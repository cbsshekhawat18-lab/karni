"""``karni recipes`` (experimental): ready-made app specs a new app starts from.

    karni recipes list [--json]                   every recipe, and the blank start
    karni recipes list --match "<request>"        the best few for a one-line request
    karni recipes show NAME [--json]              one recipe and its karni.yaml (blank: the
                                                  blank start)
    karni recipes show NAME --files               the recipe's own domain code, to copy from
    karni recipes add NAME [--no-build]           merge a recipe into this project, then build
    karni recipes remove NAME [--allow-destructive]   take a part out of this project
    karni recipes upgrade [NAME]                  each part's newer files and spec keys

The recipes come from :mod:`karni_cli.recipes`: the ones built into
karni-cli and the ``karni.recipes`` entry points of its environment.
``--match`` ranks them by plain word overlap with the request, with no
language model. ``add``, ``remove`` and ``upgrade`` keep the parts of a project
(:mod:`karni_cli.recipes.parts`, :mod:`karni_cli.recipes.compose`). See
docs/app-spec.md#recipes and docs/family.md.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

from karni_cli.project import find_project

if TYPE_CHECKING:
    from karni_cli.recipes import Loaded

recipes_app = typer.Typer(
    help=(
        "Recipes (experimental): ready-made karni.yaml files a new app starts from, matched to "
        "a one-line request (list, show), and the parts of a project (add, remove, upgrade)."
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
    has. A word that is the recipe's own noun (its name, or a use_when phrase
    of that one word) scores 4. The recipes that score 2 or more come back, best first, at most 3.
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


def _show_files(loaded: Loaded, name: str, as_json: bool) -> None:
    """``--files``: each of the recipe's own files, its path and its text."""
    from karni_cli.recipes import apply

    recipe = loaded.require(name)
    contents = apply.contents(recipe) if recipe is not None else {}
    if as_json:
        typer.echo(json.dumps({"recipe": name, "files": contents}, indent=2))
        return
    if not contents:
        typer.echo(f"{name}: no files of its own (its karni.yaml is the whole recipe).")
        return
    for rel, text in contents.items():
        typer.echo(f"--- {rel}")
        typer.echo(text.rstrip("\n"))
    typer.echo(
        f"next: copy what fits into the project's own files (karni build writes the stubs they "
        f"replace). karni new --recipe {name} writes them all into a new project."
    )


@recipes_app.command("show")
def show(
    name: str = typer.Argument(..., help="A recipe, or blank for the blank start."),
    files: bool = typer.Option(
        False,
        "--files",
        help="Print the recipe's own domain code instead: each file of its files/ folder, with "
        "the path it takes in a project (with --json: {recipe, files: {path: text}}).",
    ),
    as_json: bool = typer.Option(False, "--json", help=_JSON_HELP),
) -> None:
    """Experimental. One recipe: what it is for, what people usually change, its files and spec.

    blank shows the blank start: karni.yaml with the version and the app's
    name, nothing else, where an app starts when no recipe fits. --files prints
    the recipe's own model methods, actions, seeders and tests, which only karni
    new --recipe writes into a project.
    """
    from karni_cli.recipes import output

    loaded, app = _load()
    if files:
        _show_files(loaded, name, as_json)
        return
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
        lines.append(
            "Files (karni recipes show "
            + entry["name"]
            + " --files prints them): "
            + ", ".join(entry["files"])
        )
    lines += ["karni.yaml:", *str(entry["spec"]).rstrip("\n").splitlines()]
    lines.append(f"next: {data['next']}")
    typer.echo("\n".join(lines))


# the parts of a project ----------------------------------------------------------

_NO_BUILD_HELP = "Write karni.yaml and the record only. karni build does the rest."


def _project_spec() -> tuple[Path, Path]:
    from karni_cli.commands.spec import _default_spec
    from karni_cli.project import CliError, require_project

    root = require_project()
    spec = _default_spec()
    if not spec.is_file():
        raise CliError(
            f"No spec at {spec}. A project's parts live in its karni.yaml: export one with "
            "karni spec export -o karni.yaml first.",
            code="C210",
        )
    return root, spec


def _build(root: Path, *, allow_destructive: bool = False) -> None:
    """``karni build`` in the project. Raises ``typer.Exit(1)`` when it stops."""
    from karni_cli.commands.build import build as build_command

    typer.echo("")
    typer.echo("$ karni build")
    with contextlib.chdir(root):
        build_command(
            spec=None,
            dry_run=False,
            allow_destructive=allow_destructive,
            force=False,
            adopt=None,
            verbose=False,
            as_json=False,
            docker=None,
            service="django",
        )


@recipes_app.command("add")
def add(
    name: str = typer.Argument(..., help="The recipe to add (karni recipes list)."),
    no_build: bool = typer.Option(False, "--no-build", help=_NO_BUILD_HELP),
) -> None:
    """Experimental. Add a recipe to this project as a part, then karni build.

    The recipe's karni.yaml is merged into the project's (docs/family.md has
    the rules): its app under its own route, its roles named <prefix>-<role>,
    the family roles admin and customer adding up, what it requires switched
    on. A conflict stops it before anything is written (C442 to C447). The
    fragment is kept in .karni/recipes/<name>/, and karni build writes the
    recipe's own files by the stub rule, migrates and seeds only its new
    tables.
    """
    from karni_cli import recipes as recipes_mod
    from karni_cli.project import CliError
    from karni_cli.recipes import parts

    root, spec = _project_spec()
    loaded = recipes_mod.load()
    recipe = loaded.require(name)
    if recipe is None:
        raise CliError(
            "blank is the blank start, not a recipe to add. Name a recipe (karni recipes list).",
            code="C420",
        )
    merged = parts.add(root, spec, recipe, loaded)
    typer.echo(f"Recipe {recipe.name} ({recipe.title}): merged into {spec.name}.")
    for note in merged.notes:
        typer.echo(f"  {note}")
    if no_build:
        typer.echo(f"next: karni build (it writes {', '.join(recipe.files) or 'no files'})")
        return
    _build(root)


@recipes_app.command("remove")
def remove(
    name: str = typer.Argument(..., help="The part to take out (app.recipes)."),
    allow_destructive: bool = typer.Option(
        False,
        "--allow-destructive",
        help="Let the build drop the part's tables (C270 stops it otherwise).",
    ),
    no_build: bool = typer.Option(False, "--no-build", help=_NO_BUILD_HELP),
) -> None:
    """Experimental. Take a part out of this project, then karni build.

    Its apps, roles, pages, menu group and seed counts leave karni.yaml, and
    its record leaves .karni/recipes/. Dropping its tables is a risky change:
    pass --allow-destructive. Its files the project never changed are deleted,
    and the ones it changed stay on disk, each one listed.
    """
    from karni_cli.recipes import parts

    root, spec = _project_spec()
    _merged, done = parts.remove(root, spec, name)
    typer.echo(f"Recipe {name}: taken out of {spec.name} and {parts.PARTS_DIR}/.")
    if done.deleted:
        typer.echo("Its files you never changed are deleted: " + ", ".join(done.deleted))
    if done.kept:
        typer.echo("Its files you changed stay, for you to delete: " + ", ".join(done.kept))
    if no_build:
        typer.echo("next: karni build --allow-destructive (it drops the part's tables)")
        return
    _build(root, allow_destructive=allow_destructive)


@recipes_app.command("upgrade")
def upgrade(
    name: str | None = typer.Argument(None, help="One part (default: every part)."),
    no_build: bool = typer.Option(False, "--no-build", help=_NO_BUILD_HELP),
) -> None:
    """Experimental. Bring each part to the recipe karni-cli has now, then karni build.

    A file of the part's the project never changed (its recorded sha256) is
    replaced. A file it changed is kept, and the recipe's new file is written
    beside it as <file>.recipe-<version>. In karni.yaml, each of the part's
    entities and roles the project left as added is updated, and each one it
    changed is reported.
    """
    from karni_cli import recipes as recipes_mod
    from karni_cli.project import CliError
    from karni_cli.recipes import compose, parts
    from karni_cli.spec.source import load

    root, spec = _project_spec()
    data = load(spec.read_text(encoding="utf-8")).data
    present = compose.installed(data if isinstance(data, dict) else {})
    names = [name] if name else present
    if name and name not in present:
        raise CliError(
            f"The recipe {name} is not in this project (app.recipes lists "
            f"{', '.join(present) or 'none'}).",
            code="C448",
        )
    loaded = recipes_mod.load()
    changed = False
    for part in names:
        recipe = loaded.require(part)
        if recipe is None:
            continue
        report = parts.upgrade(root, spec, recipe)
        changed = changed or bool(report.replaced or report.added or report.spec_updated)
        for line in report.lines():
            typer.echo(line)
    if not names:
        typer.echo("This project holds no recipe (app.recipes is empty).")
        return
    if no_build or not changed:
        typer.echo("next: karni build" if changed else "Nothing to build.")
        return
    _build(root)
