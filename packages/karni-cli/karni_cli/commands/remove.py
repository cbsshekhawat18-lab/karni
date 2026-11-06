"""``karni remove <module>`` (experimental): take out what ``karni add`` wired, never the data.

What it takes out, from the module's manifest (:mod:`karni_cli.catalog`):
the dependency in ``pyproject.toml``, its apps in the ``# karni:apps``
block, its middleware and context processors (and the context processors
block once it is empty), its include in config/urls.py, the kind it gave
the project (a site+app goes back to an app), and its recorded agent
guidance, ``.karni/modules/<module>.md``, after which the agent files are
refreshed (``karni rules sync``).

It refuses when another added module requires it (``C316``). It never drops
data: it counts the rows of each of the module's tables through ``manage.py
karni_rows``, and while a table exists it stops (``C319``) with the exact
``karni migrate <app> zero`` command for the user to run deliberately,
because Django can drop a module's tables only while the module is in
``INSTALLED_APPS``. ``--keep-tables`` takes the module out and leaves the
tables. Then it prints the step that uninstalls the package.

Override / escape hatch: ``--dry-run`` prints every change and the row
counts and writes nothing. A module without a manifest is taken out by
convention (``karni_<module>``, ``karni-<module>``).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomlkit
import typer
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from karni_cli import catalog
from karni_cli.adapters import MODULES_DIR
from karni_cli.commands.add import (
    FRONTEND_PACKAGE,
    _dump_package,
    _refresh_adapters,
    find_manifest,
)
from karni_cli.project import CliError, require_project
from karni_cli.settings_edit import (
    MARKER,
    MIDDLEWARE_MARKER,
    PROCESSORS_MARKER,
    PROCESSORS_SETTING,
    block_entries,
    remove_block,
    remove_entry,
)

if TYPE_CHECKING:
    from karni.catalog import Manifest

SETTINGS = Path("config") / "settings.py"
URLS = Path("config") / "urls.py"
PYPROJECT = Path("pyproject.toml")
#: Folders the scan for leftover references never enters.
_SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".karni", "dist"})
_SCAN_SUFFIXES = (".py", ".html")
_SCAN_CAP = 10

#: ``requests -> {"rows": [...], "unreachable": {...}}``, as ``manage.py karni_rows`` prints.
Counter = Callable[[list[dict[str, Any]]], dict[str, Any]]


def remove_dependency_text(text: str, distribution: str) -> str | None:
    """``pyproject.toml`` text without ``distribution`` in [project].dependencies.

    The reverse of :func:`karni_cli.commands.add.add_dependency_text`, parsed
    with tomlkit. ``None`` when the table does not name it (extras and
    version specifiers included).
    """
    doc = tomlkit.parse(text)
    try:
        deps = doc["project"]["dependencies"]
    except (KeyError, TypeError):
        return None
    target = canonicalize_name(distribution)
    for index, dep in enumerate(list(deps)):
        try:
            if canonicalize_name(Requirement(str(dep)).name) == target:
                del deps[index]
                return tomlkit.dumps(doc)
        except InvalidRequirement:
            continue
    return None


def remove_ui_dependency_text(text: str, package: str) -> str | None:
    """``frontend/package.json`` text without ``package`` in dependencies, ``None`` if absent.

    The reverse of :func:`karni_cli.commands.add.ui_dependency_text`. An empty
    ``dependencies`` table the add created is left out again.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    deps = data.get("dependencies") if isinstance(data, dict) else None
    if not isinstance(deps, dict) or package not in deps:
        return None
    del deps[package]
    return _dump_package(data, text)


def remove_include(text: str, app: str) -> tuple[str | None, bool]:
    """config/urls.py ``text`` without the one-line ``path(..., include("<app>.urls"))``.

    Returns the new text (``None``: no such line) and whether the include is
    still named elsewhere (a call split over lines, which is left alone).
    """
    include = re.compile(rf"""include\(\s*["']{re.escape(app)}\.urls["']""")
    lines = text.splitlines()
    kept = [
        line for line in lines if not (line.strip().startswith("path(") and include.search(line))
    ]
    rest = any(include.search(line) and not line.lstrip().startswith("#") for line in kept)
    if len(kept) == len(lines):
        return None, rest
    return "\n".join(kept) + "\n", rest


@dataclass
class Removal:
    """Experimental. What ``karni remove`` changes: new file texts, deletions, and why."""

    texts: dict[Path, str] = field(default_factory=dict)
    deletes: list[Path] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def edit(self, path: Path, text: str, change: str) -> None:
        self.texts[path] = text
        self.changes.append(f"{path.as_posix()}: {change}")


def _owned(entry: str, apps: list[str], paths: set[str]) -> bool:
    """An entry the module wired: one its manifest names, or any dotted path inside its apps."""
    return entry in paths or any(entry == app or entry.startswith(f"{app}.") for app in apps)


def plan_removal(project: Path, name: str, manifest: Manifest | None) -> Removal:
    """Experimental. Every change that takes the module out of ``project``, nothing written."""
    from karni_cli import kinds

    app = manifest.app if manifest else f"karni_{name.replace('-', '_')}"
    apps = list(manifest.wiring.apps) if manifest else [app]
    distribution = manifest.distribution if manifest else f"karni-{name.replace('_', '-')}"
    removal = Removal()

    pyproject = project / PYPROJECT
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        updated = remove_dependency_text(text, distribution)
        if updated is not None:
            removal.edit(PYPROJECT, updated, f"{distribution} removed from [project].dependencies")
            text = updated
        if manifest is not None and manifest.wiring.kind == "site":
            kind = kinds.recorded_kind(text)
            if kind == "site+app":
                removal.edit(PYPROJECT, kinds.set_kind_text(text, "app"), "kind: site+app -> app")
            elif kind == "site":
                removal.notes.append(
                    'pyproject.toml keeps kind = "site": a site without karni-site has no '
                    "content to edit. Set the kind under [tool.karni] yourself."
                )

    settings = project / SETTINGS
    if settings.is_file():
        text = settings.read_text(encoding="utf-8")
        before = text
        wiring = manifest.wiring if manifest else None
        paths = (
            {e.path for e in (*wiring.middleware, *wiring.context_processors)} if wiring else set()
        )
        processors_out = False
        for setting, marker, label in (
            ("INSTALLED_APPS", MARKER, "INSTALLED_APPS"),
            ("MIDDLEWARE", MIDDLEWARE_MARKER, "MIDDLEWARE"),
            (PROCESSORS_SETTING, PROCESSORS_MARKER, "the context processors"),
        ):
            for entry in block_entries(text, setting, marker):
                updated = (
                    remove_entry(text, entry, setting=setting, marker=marker)
                    if _owned(entry, apps, paths)
                    else None
                )
                if updated is not None:
                    text = updated
                    processors_out = processors_out or marker == PROCESSORS_MARKER
                    removal.changes.append(f"{SETTINGS.as_posix()}: {entry} out of {label}")
        emptied = remove_block(text, PROCESSORS_SETTING, PROCESSORS_MARKER)
        if processors_out and emptied is not None:
            text = emptied
            removal.changes.append(f"{SETTINGS.as_posix()}: the empty context processors block")
        if text != before:
            removal.texts[SETTINGS] = text
        for setting in manifest.provides.settings if manifest else ():
            if re.search(rf"^\s*{setting}\s*=", text, re.MULTILINE):
                removal.notes.append(
                    f"{SETTINGS.as_posix()} still sets {setting}: delete it once nothing reads it."
                )

    urls = project / URLS
    if urls.is_file():
        for module_app in apps:
            updated, rest = remove_include(urls.read_text(encoding="utf-8"), module_app)
            if updated is not None:
                removal.edit(URLS, updated, f"the include of {module_app}.urls removed")
            if rest:
                removal.notes.append(
                    f"{URLS.as_posix()} still includes {module_app}.urls on more than one line: "
                    "remove it yourself."
                )

    package = manifest.provides.ui if manifest else ""
    frontend = project / FRONTEND_PACKAGE
    if package and frontend.is_file():
        updated_package = remove_ui_dependency_text(frontend.read_text(encoding="utf-8"), package)
        if updated_package is not None:
            removal.edit(
                Path(FRONTEND_PACKAGE), updated_package, f"{package} removed from dependencies"
            )

    fragment = MODULES_DIR / f"{name}.md"
    if (project / fragment).is_file():
        removal.deletes.append(fragment)
        removal.changes.append(f"{fragment.as_posix()}: deleted (its agent guidance)")
    return removal


def _counts(
    project: Path, app: str, models: tuple[str, ...], counter: Counter | None
) -> tuple[list[tuple[str, str, int | None]], str]:
    """``(table, model, rows)`` for each model, and why there are no counts (``""``: counted)."""
    if not models:
        return [], "its manifest names no models"
    labels = [f"{app}.{model}" for model in models]
    if counter is None:
        return [], "no counter"
    try:
        answer = counter([{"model": label} for label in labels])
    except CliError as exc:
        return [], exc.message
    rows = list(answer.get("rows") or [])
    if answer.get("error") or len(rows) != len(labels):
        return [], str(answer.get("error") or "the counts did not come back")
    unreachable = answer.get("unreachable") or {}
    if unreachable:
        return [], "the database did not answer (" + ", ".join(unreachable.values()) + ")"
    found = [
        (f"{app}_{model.lower()}", label, count if isinstance(count, int) else None)
        for model, label, count in zip(models, labels, rows, strict=True)
    ]
    return found, ""


def _table_lines(counts: list[tuple[str, str, int | None]], why: str) -> list[str]:
    if why:
        return [f"Row counts not available: {why}. Nothing is dropped either way."]
    lines = ["Its tables (nothing is dropped):"]
    for table, label, rows in counts:
        lines.append(
            f"  {table} ({label}): " + (f"{rows} rows" if rows is not None else "no table")
        )
    return lines


def _references(project: Path, app: str) -> list[str]:
    """Project files (Python, templates) that still name the app."""
    pattern = re.compile(rf"\b{re.escape(app)}\b")
    found: list[str] = []
    for folder, dirs, files in os.walk(project):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for filename in sorted(files):
            if not filename.endswith(_SCAN_SUFFIXES):
                continue
            path = Path(folder) / filename
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if pattern.search(text):
                found.append(path.relative_to(project).as_posix())
    return found


def _default_counter(project: Path) -> Counter:
    from karni_cli.spec.plan import manage_counter

    return manage_counter(project)


def _tables_message(name: str, app: str, tables: list[str]) -> str:
    return (
        f"{name}'s tables exist ({', '.join(tables)}), and Django can drop them only while "
        f"{app} is in INSTALLED_APPS. To drop them and their rows, run deliberately:\n"
        f"  karni migrate {app} zero\n"
        f"then karni remove {name} again. To keep them in the database: karni remove {name} "
        "--keep-tables."
    )


def remove(
    module: str = typer.Argument(..., help='Module short name, e.g. "payments"'),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print every change and each table's rows. Write nothing."
    ),
    keep_tables: bool = typer.Option(
        False,
        "--keep-tables",
        help="Take the module out although its tables exist: they stay in the database.",
    ),
) -> None:
    """Experimental. Take out what karni add wired. Never drops data.

    It takes the dependency out of pyproject.toml, the module's apps,
    middleware and context processors out of config/settings.py, its include
    out of config/urls.py and its agent guidance out of .karni/modules/, then
    refreshes the agent files. It refuses while another added module requires
    it. It counts the rows of the module's tables: while a table exists it
    stops and prints the `karni migrate <app> zero` command that drops them
    (run it deliberately, then karni remove again), unless --keep-tables.
    """
    project = require_project()
    manifest, loaded = find_manifest(project, module)
    name = manifest.name if manifest else module
    app = manifest.app if manifest else f"karni_{module.replace('-', '_')}"
    distribution = manifest.distribution if manifest else f"karni-{module.replace('_', '-')}"
    removal = plan_removal(project, name, manifest)
    if not removal.changes:
        raise CliError(
            f"{name} is not in this project: no {distribution} in pyproject.toml, no {app} in "
            "config/settings.py and no recorded guidance. Nothing to remove.",
            code="C317",
        )
    if loaded.installed is None:  # the modules installed in the project may require it too
        loaded = catalog.load(project)
    needing = loaded.requiring(name, loaded.added - {name})
    if needing:
        raise CliError(
            f"{', '.join(needing)} requires {name}. Remove {needing[0]} first: karni remove "
            f"{needing[0]}.",
            code="C316",
        )
    wired = app in block_entries((project / SETTINGS).read_text(encoding="utf-8"))
    counts, why = (
        _counts(
            project, app, manifest.provides.models if manifest else (), _default_counter(project)
        )
        if wired
        else ([], f"{app} is not in INSTALLED_APPS, so Django does not know its tables")
    )
    tables = [table for table, _, rows in counts if rows is not None]
    stops = bool(tables) and not keep_tables
    if stops and not dry_run:
        raise CliError(_tables_message(name, app, tables), code="C319")
    header = "Would change (--dry-run, nothing written):" if dry_run else "Changes:"
    typer.echo(header)
    for change in removal.changes:
        typer.echo(f"  {change}")
    if removal.deletes or not dry_run:
        typer.echo("  the agent files: refreshed (karni rules sync)")
    for line in _table_lines(counts, why):
        typer.echo(line)
    if stops:
        typer.echo(f"karni remove would stop here (C319): {_tables_message(name, app, tables)}")
        return
    if dry_run:
        for note in removal.notes:
            typer.echo(note)
        return
    for path, text in removal.texts.items():
        (project / path).write_text(text, encoding="utf-8")
    for path in removal.deletes:
        (project / path).unlink()
        folder = (project / path).parent
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    _refresh_adapters(project)
    for note in removal.notes:
        typer.echo(note)
    if tables or (wired and why and manifest is not None and manifest.provides.models):
        typer.echo(
            ("Its tables stay in the database" if tables else "Any tables it has stay")
            + f". To drop them later: karni add {name}, karni migrate {app} zero, then karni "
            f"remove {name}."
        )
    leftovers = _references(project, app)
    if leftovers:
        shown = ", ".join(leftovers[:_SCAN_CAP]) + (" ..." if len(leftovers) > _SCAN_CAP else "")
        typer.echo(f"Still named in your code (it fails once uninstalled): {shown}")
    typer.echo("Uninstall it:")
    typer.echo(f"  uv pip uninstall {distribution}   # host venv workflow")
    typer.echo("  docker compose build        # container workflow")
