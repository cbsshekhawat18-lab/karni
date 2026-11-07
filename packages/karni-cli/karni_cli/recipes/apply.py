"""Experimental. A recipe's own files written into a project, over the stubs of ``karni build``.

``karni new "<Name>" --recipe <name>`` writes the recipe's ``karni.yaml``
and names the recipe in ``.karni/build.json``. The first ``karni build``
that writes then calls :func:`stage` right after it renders its own files:
each file of the recipe's ``files/`` folder goes to the same path in the
project (``files/shop/models.py`` is ``shop/models.py``), before the
migrations, the seed and the tests run, so the demo data comes from the
recipe's seeders and its tests run with the rest.

The stub rule: a recipe's file goes only where nothing is lost. The
project's file must be missing, the recipe's already, or still exactly what
``karni build`` writes in it (:func:`karni_cli.builder.render.is_stub_file`:
its docstring, its imports and a stub class per entity). Anything else stops
the build with ``C441`` before any file is written, naming each file.

A class that build writes for an entity the recipe's file does not have (an
entity added to karni.yaml before the first build) is kept: it goes after the
recipe's code, so every entity still has its class.

Override / escape hatch: :func:`stage` takes any
:class:`~karni_cli.recipes.Recipe`, an installed one too, and
:func:`contents` reads a recipe's files for a tool of your own.
"""

from __future__ import annotations

import ast
from typing import Final

from karni_cli.builder.render import is_stub_file
from karni_cli.generators.core import Workspace
from karni_cli.generators.pysource import Import, ensure_imports, parse
from karni_cli.project import CliError
from karni_cli.recipes import FILES_DIR, Recipe

__all__ = ["RECORD_KEY", "contents", "refused", "stage"]

#: Experimental. The key of ``.karni/build.json`` that names the recipe the next build writes.
RECORD_KEY: Final = "recipe"


def contents(recipe: Recipe) -> dict[str, str]:
    """Experimental. The recipe's own files: the path each takes in the project, and its text."""
    return {
        rel: recipe.folder.joinpath(FILES_DIR, *rel.split("/")).read_text(encoding="utf-8")
        for rel in recipe.files
    }


def _on_disk(ws: Workspace, rel: str) -> str | None:
    path = ws.path(rel)
    return path.read_text(encoding="utf-8") if path.is_file() else None


def refused(ws: Workspace, recipe: Recipe) -> list[str]:
    """Experimental. The recipe's files the stub rule keeps out: the project's code is there."""
    found = []
    for rel, text in contents(recipe).items():
        current = _on_disk(ws, rel)
        if current is None or current == text:
            continue
        if rel.endswith(".py") and is_stub_file(rel, current):
            continue
        found.append(rel)
    return found


def _kept_classes(ws: Workspace, rel: str, stub: str, text: str) -> str:
    """``text`` with each class of build's ``stub`` that ``text`` lacks, and its imports."""
    theirs = parse(ws, rel, stub)
    have = {node.name for node in parse(ws, rel, text).body if isinstance(node, ast.ClassDef)}
    missing = [n for n in theirs.body if isinstance(n, ast.ClassDef) and n.name not in have]
    if not missing:
        return text
    imports = [
        Import(node.module, alias.name, alias.asname, node.level)
        for node in theirs.body
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    ]
    text = ensure_imports(ws, rel, text, imports)
    blocks = [ast.get_source_segment(stub, node) or "" for node in missing]
    return text.rstrip("\n") + "\n\n\n" + "\n\n\n".join(blocks) + "\n"


def stage(ws: Workspace, recipe: Recipe) -> list[str]:
    """Experimental. Plan the recipe's own files into ``ws``, over build's stubs.

    Returns the paths whose content changes.

    :raises CliError: ``C441`` when a file of the project's holds code of its
        own where the recipe has a file. Nothing is planned then.
    """
    blocked = refused(ws, recipe)
    if blocked:
        listed = ", ".join(blocked)
        raise CliError(
            f"{listed} {'holds' if len(blocked) == 1 else 'hold'} code of the project's, and the "
            f"recipe {recipe.name} has its own file there, so karni build wrote nothing. A recipe "
            "writes only over the stubs karni build writes. Move your code out of the way (rename "
            "the file), run karni build again, then put your code back into the recipe's file. "
            f'To build without the recipe\'s files, delete "{RECORD_KEY}" from .karni/build.json.',
            code="C441",
        )
    staged = []
    for rel, text in contents(recipe).items():
        current = ws.read(rel)
        if current is not None and rel.endswith(".py") and current != text:
            text = _kept_classes(ws, rel, current, text)
        if current != text:
            ws.write(rel, text)
            staged.append(rel)
    return staged
