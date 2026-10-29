"""``karni design analyze`` and ``karni design extract``: a design's content as models and rows.

``analyze`` reads a folder of static pages (the one ``karni import design``
imports) and proposes the models its repeated content needs, with ready-to-run
``karni make model`` commands, and the relations the markup cannot settle as
decisions for the agent. ``--map FILE`` writes a draft content map.

``extract`` reads the pages with that map and writes their content in the
``karni load`` format, image paths relative to the output file, so
``karni load`` fills the models with the designer's real content. See
:mod:`karni_cli.design.analyze` and :mod:`karni_cli.design.extract`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer

from karni_cli.design.analyze import Analysis
from karni_cli.design.analyze import analyze as run_analysis
from karni_cli.design.extract import MapError, read_map
from karni_cli.design.extract import extract as run_extract
from karni_cli.design.site import DESIGN_RECORD
from karni_cli.project import CliError

design_app = typer.Typer(
    help="Read a designer's pages: the models their content needs, and the content itself.",
    no_args_is_help=True,
    add_completion=False,
)


def _design_dir(directory: Path) -> Path:
    if not directory.is_dir():
        raise CliError(
            f"{directory} is not a directory. Pass the folder that holds the design's HTML "
            "pages (index.html, about.html, ...).",
            code="C111",
        )
    return directory.resolve()


def _app_label(app: str | None) -> str:
    """``--app``, else the app ``karni import design`` recorded, else ``website``."""
    if app:
        return app
    for folder in (Path.cwd(), *Path.cwd().parents):
        record = folder / DESIGN_RECORD
        if record.is_file():
            try:
                found = json.loads(record.read_text(encoding="utf-8")).get("app")
            except (OSError, json.JSONDecodeError):
                break
            if found:
                return str(found)
            break
        if (folder / "manage.py").is_file():
            break
    return "website"


def _label(path: Path) -> str:
    try:
        return os.path.relpath(path, Path.cwd())
    except ValueError:
        return str(path)


def analyze_design(
    source: Path,
    app: str,
    *,
    map_file: Path | None = None,
    force: bool = False,
    label: str | None = None,
) -> Analysis:
    """The analysis of the design folder ``source``, with its draft map written to ``map_file``.

    The command's work without the printing: ``karni new --design`` calls it.
    """
    try:
        analysis = run_analysis(source, app, label=label or str(source))
    except ValueError as exc:
        raise CliError(str(exc), code="C111") from None
    if map_file is not None:
        if map_file.exists() and not force:
            raise CliError(
                f"{map_file} is there already, and it may hold your edits. Pass --force to "
                "replace it, or write the draft to another file.",
                code="C123",
            )
        map_file.parent.mkdir(parents=True, exist_ok=True)
        design_label = Path(os.path.relpath(source, map_file.parent.resolve())).as_posix()
        data = analysis.draft_map(design_label)
        map_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return analysis


@design_app.command("analyze")
def analyze(
    directory: Path = typer.Argument(..., help="The folder with the design's HTML pages."),
    app: str | None = typer.Option(
        None,
        "--app",
        help="The app the models go in (default: the app karni import design used, else website).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the analysis as JSON."),
    map_file: Path | None = typer.Option(
        None,
        "--map",
        help="Write a draft content map to this file, for karni design extract.",
    ),
    force: bool = typer.Option(False, "--force", help="Replace a map file that is there."),
) -> None:
    """Find the content that repeats in a design and propose models for it.

    Reads every page, sets aside what every page shares (the header, the
    footer), and finds the structures that repeat within and across pages:
    cards, list items, a gallery inside each project, a page per doctor. For
    each it infers the fields from the markup (a heading with its highlighted
    words, text, an image with its alt text, a link to another page, a list
    of tags, a date, a price, a number) and the relations between them (a
    card that links to a detail page is that page's model, a list of links
    to other items is a relation). Names come from the design's classes,
    headings and pages. It prints ready-to-run `karni make model` commands,
    models others point at first, and the decisions the markup cannot settle
    (a hand-picked list, or one a query derives).

    --map writes a draft content map: which structure is which model and
    which element is which field. Edit it, answer its decisions, then run
    `karni design extract`.

    Example: karni design analyze ../design --map content/design-map.json
    """
    source = _design_dir(directory)
    analysis = analyze_design(
        source, _app_label(app), map_file=map_file, force=force, label=_label(source)
    )
    if as_json:
        typer.echo(json.dumps(analysis.to_dict(), indent=2, ensure_ascii=False))
        return
    typer.echo(analysis.render())
    if map_file is not None:
        typer.echo("")
        typer.echo(f"wrote the draft map {map_file}.")
    typer.echo("")
    typer.echo(
        "next: run the commands, answer the decisions in the map, then "
        "karni design extract <design> --map <map> and karni load <content file>."
    )


@design_app.command("extract")
def extract(
    directory: Path = typer.Argument(..., help="The folder with the design's HTML pages."),
    map_file: Path = typer.Option(
        ..., "--map", help="The content map (karni design analyze --map writes a draft)."
    ),
    output: Path = typer.Option(
        Path("content/site.json"),
        "--output",
        "-o",
        help="The content file to write, in the karni load format.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print what would be written and write nothing."
    ),
) -> None:
    """Write the design's content as a `karni load` file, read with a content map.

    Each model's rows come from the pages the map names: a row per item (or
    per detail page), keyed so the same item read on several pages is one
    row, its fields read from the elements the map gives and parsed by the
    field's type. Relations name their rows by key, child rows (a gallery)
    nest under their parent, and image paths are relative to the output
    file, so `karni load` uploads the designer's own images. The map's open
    decisions must be answered first.

    Example: karni design extract ../design --map content/design-map.json -o content/site.json
    """
    source = _design_dir(directory)
    try:
        spec: dict[str, Any] = read_map(map_file)
        result = run_extract(source, spec, output)
    except MapError as exc:
        if exc.pending:
            raise CliError(str(exc), code="C122") from None
        raise CliError(str(exc), code="C121") from None
    text = json.dumps(result.content, indent=2, ensure_ascii=False) + "\n"
    if dry_run:
        typer.echo(text)
        typer.echo(result.render(f"{output} (--dry-run: nothing written)"))
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    previous = output.read_text(encoding="utf-8") if output.is_file() else None
    output.write_text(text, encoding="utf-8")
    typer.echo(result.render(str(output)))
    if previous == text:
        typer.echo("The content is unchanged since the last extract.")
    typer.echo("")
    typer.echo(f"next: karni load {output} --dry-run, then karni load {output}.")
