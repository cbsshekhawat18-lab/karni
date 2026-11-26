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

A file ``karni new`` wrote (``frontend/src/layout.tsx``,
``frontend/src/pages/home.tsx``) counts as a stub too while it is exactly
what ``karni new`` wrote: ``karni new --recipe`` records its sha256 in
``.karni/build.json`` (``scaffold``, :func:`scaffold_digests`).

A class that build writes for an entity the recipe's file does not have (an
entity added to karni.yaml before the first build) is kept: it goes after the
recipe's code, so every entity still has its class.

Then each ``[[routes]]`` entry of the recipe is registered in
``frontend/src/routes.tsx`` at the ``// karni:page-imports`` and
``// karni:routes`` markers, as ``karni make page`` registers a page: the
page's import, and ``createRoute({..., path, component})`` with
``staticData: { public: true }`` for a page a visitor sees without signing
in. A route the file has already is left alone.

Override / escape hatch: :func:`stage` takes any
:class:`~karni_cli.recipes.Recipe`, an installed one too, and
:func:`contents` reads a recipe's files for a tool of your own.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from karni_cli.builder.render import is_stub_file
from karni_cli.generators.core import Workspace
from karni_cli.generators.page import IMPORT_MARKER, ROUTE_MARKER, ROUTES, known_routes
from karni_cli.generators.pysource import Import, ensure_imports, parse
from karni_cli.project import CliError
from karni_cli.recipes import FILES_DIR, Recipe, RecipeRoute

__all__ = ["RECORD_KEY", "contents", "refused", "route_lines", "scaffold_digests", "stage"]

#: The key of ``.karni/build.json`` that names the recipes the next build writes.
RECORD_KEY: Final = "recipes"


def contents(recipe: Recipe) -> dict[str, str]:
    """The recipe's own files: the path each takes in the project, and its text."""
    return {
        rel: recipe.folder.joinpath(FILES_DIR, *rel.split("/")).read_text(encoding="utf-8")
        for rel in recipe.files
    }


def _on_disk(ws: Workspace, rel: str) -> str | None:
    path = ws.path(rel)
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scaffold_digests(project: Path, recipe: Recipe) -> dict[str, str]:
    """The sha256 of each file of ``project`` where ``recipe`` has a file of its own.

    ``karni new --recipe`` records them right after it writes the project, so
    the first build replaces those files only while they are still what
    ``karni new`` wrote. Python files are left out: build's stubs have their
    own rule (:func:`~karni_cli.builder.render.is_stub_file`).
    """
    found: dict[str, str] = {}
    for rel in recipe.files:
        path = project.joinpath(*rel.split("/"))
        if not rel.endswith(".py") and path.is_file():
            found[rel] = _digest(path.read_text(encoding="utf-8"))
    return found


def refused(ws: Workspace, recipe: Recipe, scaffold: Mapping[str, str] | None = None) -> list[str]:
    """The recipe's files the stub rule keeps out: the project's code is there.

    ``scaffold`` maps a file to the sha256 ``karni new`` recorded for it
    (:func:`scaffold_digests`): such a file is a stub while it still has it.
    """
    stubs = scaffold or {}
    found = []
    for rel, text in contents(recipe).items():
        current = _on_disk(ws, rel)
        if current is None or current == text:
            continue
        if rel.endswith(".py") and is_stub_file(rel, current):
            continue
        if rel in stubs and stubs[rel] == _digest(current):
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


def route_lines(route: RecipeRoute) -> tuple[str, str]:
    """The import and the ``createRoute(...)`` line ``route`` adds to the routes file."""
    module = route.page
    import_line = f'import {route.component} from "./{module}";'
    values = {**({"public": True} if route.public else {}), **route.data}
    pairs = ", ".join(
        f"{key}: {'true' if value is True else 'false' if value is False else json.dumps(value)}"
        for key, value in values.items()
    )
    data = f", staticData: {{ {pairs} }}" if pairs else ""
    line = (
        f'    createRoute({{ getParentRoute: () => root, path: "{route.path}", '
        f"component: {route.component}{data} }}),"
    )
    return import_line, line


def _register_routes(ws: Workspace, recipe: Recipe) -> None:
    if not recipe.routes:
        return
    text = ws.read(ROUTES)
    if text is None or IMPORT_MARKER not in text or ROUTE_MARKER not in text:
        raise CliError(
            f"The recipe {recipe.name} registers its pages in {ROUTES.as_posix()} at the "
            f"`{IMPORT_MARKER}` and `{ROUTE_MARKER}` markers, and the file or a marker is "
            "missing. Put both markers back (karni new writes them), then run karni build again.",
            code="C284",
        )
    existing = known_routes(ws)
    lines = text.splitlines()
    for route in recipe.routes:
        if route.path in existing:
            continue
        import_line, line = route_lines(route)
        if import_line not in lines:
            lines.insert(next(i for i, ln in enumerate(lines) if IMPORT_MARKER in ln), import_line)
        index = next(i for i, ln in enumerate(lines) if ROUTE_MARKER in ln)
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines.insert(index, indent + line.strip())
    ws.write(ROUTES, "\n".join(lines) + "\n")


def stage(ws: Workspace, recipe: Recipe, *, scaffold: Mapping[str, str] | None = None) -> list[str]:
    """Plan the recipe's own files into ``ws``, over build's stubs, and its routes.

    ``scaffold`` holds the digests ``karni new`` recorded (:func:`scaffold_digests`).
    Returns the paths whose content changes.

    :raises CliError: ``C441`` when a file of the project's holds code of its
        own where the recipe has a file. Nothing is planned then. ``C284``
        when the recipe has routes and the routes file has no markers.
    """
    blocked = refused(ws, recipe, scaffold)
    if blocked:
        listed = ", ".join(blocked)
        raise CliError(
            f"{listed} {'holds' if len(blocked) == 1 else 'hold'} code of the project's, and the "
            f"recipe {recipe.name} has its own file there, so karni build wrote nothing. A recipe "
            "writes only over the stubs karni build writes. Move your code out of the way (rename "
            "the file), run karni build again, then put your code back into the recipe's file. "
            f'To build without the recipe\'s files, delete it from "{RECORD_KEY}" in '
            ".karni/build.json.",
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
    _register_routes(ws, recipe)
    return staged
