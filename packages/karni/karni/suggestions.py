"""Experimental. Suggestions from code: what Karni could do that the project does by hand.

``karni check`` and ``karni doctor`` print them after the errors and
warnings. A suggestion never fails a run and never changes an exit code: it
names the file and line, and the exact command or change. Each has a stable
code in the ``SUG`` series (``karni explain SUG001``).

====== ========================= ==================================================
Code   Silencing rule            What it points out
====== ========================= ==================================================
SUG001 ``suggest-tree-model``    a foreign key to itself named like a parent
SUG002 ``suggest-markdown``      long text that holds markdown, not a MarkdownField
SUG003 ``suggest-aggregate``     raw SQL with GROUP BY, opted out of the raw-sql rule
SUG004 ``suggest-taxonomy``      three models with a many-to-many to one tree model
SUG005 ``suggest-unused-module`` an added module nothing in the project uses
SUG006 ``suggest-add-module``    a module the spec or README describes, not added
SUG007 ``suggest-sync-spec``     the project drifted from karni.yaml
====== ========================= ==================================================

This module holds the detectors that read the running project (SUG001 to
SUG005, :func:`detect`). karni-cli adds SUG006 and SUG007, which read
``karni.yaml``, the README and the module catalog, and merges both lists.

SUG001 leaves the names the ``hand-written-tree`` architecture rule already
fails on (``parent`` and ``parent_*``): the rule is stricter, and two reports
for one field help nobody.

Silencing, in the same comment form as the architecture rules, a reason
required, on the line, the line above, or (for a model) the class line::

    # karni: allow(suggest-tree-model): the rows are not a tree
    category_parent = models.ForeignKey("self", null=True, on_delete=models.PROTECT)

A marker without a reason does not silence a suggestion, and never fails the
run either. ``KARNI_SUGGESTIONS = False`` turns every suggestion off for the
project.

Override / escape hatch: the marker per line, the setting per project, and
:func:`detect` takes the detectors to run. A threshold (:data:`AGGREGATE_MIN`,
:data:`TAXONOMY_MIN`) is a module constant a project may not change: a
suggestion that fires too early is silenced, not tuned.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.apps import apps
from django.conf import settings
from django.db import models

__all__ = [
    "AGGREGATE_MIN",
    "RULES",
    "TAXONOMY_MIN",
    "VERSION",
    "Suggestion",
    "detect",
    "enabled",
    "render",
]

#: The version of the JSON output (``docs/assets/karni-suggestions.schema.json``).
VERSION = 1
#: Raw SQL opt-outs with GROUP BY from which the aggregate declaration is suggested.
AGGREGATE_MIN = 2
#: Models with a many-to-many to one tree model from which a taxonomy is suggested.
TAXONOMY_MIN = 3

#: code -> the rule id a ``# karni: allow(<rule>): <reason>`` marker names.
RULES: dict[str, str] = {
    "SUG001": "suggest-tree-model",
    "SUG002": "suggest-markdown",
    "SUG003": "suggest-aggregate",
    "SUG004": "suggest-taxonomy",
    "SUG005": "suggest-unused-module",
    "SUG006": "suggest-add-module",
    "SUG007": "suggest-sync-spec",
}

_NO_REASON = " (A karni: allow marker without a reason does not silence it.)"
_MARKDOWN_NAME = re.compile(r"(^|_)(markdown|md)$")
_MARKDOWN_HELP = re.compile(r"\bmarkdown\b", re.IGNORECASE)
_GROUP_BY = re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)
_ALLOW = re.compile(r"(?:#|<!--)\s*karni:\s*allow\(([^)]+)\)\s*:\s*(.*?)\s*(?:-->)?$")
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".karni",
        "dist",
        "build",
        "staticfiles",
    }
)
_SCAN_SUFFIXES = (".py", ".html", ".ts", ".tsx", ".yaml", ".yml")
_MAX_SCAN_BYTES = 1_000_000


@dataclass(frozen=True)
class Suggestion:
    """One suggestion: where, what, and the exact change or command."""

    code: str
    file: str
    line: int | None
    message: str
    fix: str
    #: The exact command to run, when the fix is one (``karni remove charts``).
    command: str | None = None

    @property
    def rule(self) -> str:
        return RULES[self.code]

    @property
    def location(self) -> str:
        if self.line is None:
            return self.file
        return f"{self.file}:{self.line}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "rule": self.rule,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "fix": self.fix,
            "command": self.command,
        }


def enabled() -> bool:
    """Whether the project wants suggestions (``KARNI_SUGGESTIONS``, default on)."""
    return bool(getattr(settings, "KARNI_SUGGESTIONS", True))


def render(items: Iterable[dict[str, Any]], *, title: str = "suggestions") -> str:
    """The compact block ``karni check`` and ``karni doctor`` print: one entry per suggestion.

    ``items`` are :meth:`Suggestion.as_dict` rows. An empty list renders as ``""``.
    """
    rows = list(items)
    if not rows:
        return ""
    lines = [f"{title} ({len(rows)}), they never fail the run:"]
    for row in rows:
        where = row["file"] if row["line"] is None else f"{row['file']}:{row['line']}"
        lines.append(f"  [{row['code']}] {where}: {row['message']}")
        lines.append(f"      fix: {row['fix']}")
    lines.append(
        "  Silence one with `# karni: allow(<rule>): <reason>`, see `karni explain <code>`."
    )
    return "\n".join(lines)


# markers ---------------------------------------------------------------------------


def _file_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def marker(lines: list[str], rule: str, candidates: Iterable[int]) -> str | None:
    """``"silenced"``, ``"no-reason"`` or ``None``: the marker for ``rule`` on a candidate line.

    ``lines`` are the file's lines, ``candidates`` 1-based line numbers.
    """
    found: str | None = None
    for number in candidates:
        if not 1 <= number <= len(lines):
            continue
        match = _ALLOW.search(lines[number - 1])
        if match is None:
            continue
        rules = [name.strip() for name in match.group(1).split(",")]
        if rule not in rules:
            continue
        if match.group(2).strip():
            return "silenced"
        found = "no-reason"
    return found


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _root() -> Path:
    from karni.testing._source import project_root

    return project_root()


# models ----------------------------------------------------------------------------


def _model_lines(model: type[models.Model]) -> tuple[Path, list[str], int] | None:
    """The model's file, its lines and the 1-based line of its ``class`` statement."""
    try:
        file = inspect.getsourcefile(model)
        source, first = inspect.getsourcelines(model)
    except (OSError, TypeError):
        return None
    if file is None:
        return None
    path = Path(file)
    for offset, text in enumerate(source):
        if text.lstrip().startswith("class "):
            return path, _file_lines(path), first + offset
    return path, _file_lines(path), first


def _field_line(lines: list[str], class_line: int, name: str) -> int:
    """The 1-based line that assigns ``name`` in the class, else the class line."""
    pattern = re.compile(rf"^\s+{re.escape(name)}\s*[:=]")
    for number in range(class_line, len(lines) + 1):
        if pattern.match(lines[number - 1]):
            return number
    return class_line


def _project_models() -> list[type[models.Model]]:
    from karni.testing._source import project_app_configs

    found: list[type[models.Model]] = []
    for config in project_app_configs():
        for model in config.get_models():
            if not (model._meta.auto_created or model._meta.proxy):
                found.append(model)
    return sorted(found, key=lambda m: m._meta.label)


def _field_suggestion(
    model: type[models.Model], name: str, rule: str
) -> tuple[Path, int, bool] | None:
    """Where field ``name`` is written, or ``None`` when a marker with a reason silences it.

    The last value says whether a marker without a reason sits there.
    """
    located = _model_lines(model)
    if located is None:
        return None
    path, lines, class_line = located
    line = _field_line(lines, class_line, name)
    state = marker(lines, rule, (line, line - 1, class_line, class_line - 1))
    if state == "silenced":
        return None
    return path, line, state == "no-reason"


def suggest_tree_models() -> list[Suggestion]:
    """SUG001: a foreign key to the model itself, named like a parent, on a model not a tree."""
    from karni.models import TreeModel

    root = _root()
    found: list[Suggestion] = []
    for model in _project_models():
        if issubclass(model, TreeModel):
            continue
        for field in model._meta.concrete_fields:
            name = str(field.name)
            if not (field.many_to_one and field.related_model is model and "parent" in name):
                continue
            if name == "parent" or name.startswith("parent_"):
                continue  # the hand-written-tree rule reports these
            where = _field_suggestion(model, name, RULES["SUG001"])
            if where is None:
                continue
            path, line, no_reason = where
            found.append(
                Suggestion(
                    "SUG001",
                    _relative(path, root),
                    line,
                    f"{model.__name__}.{name} is a foreign key to {model.__name__} itself: a "
                    "hand-written tree, without cycle-safe queries, tree endpoints or a tree UI."
                    + (_NO_REASON if no_reason else ""),
                    f"inherit karni.models.TreeModel first (class {model.__name__}(TreeModel, "
                    f"BaseModel)) and drop the {name} field, then run karni migrate. Or "
                    "silence it with `# karni: allow(suggest-tree-model): <reason>`.",
                )
            )
    return found


def suggest_markdown_fields() -> list[Suggestion]:
    """SUG002: a TextField named ``*_markdown`` or ``*_md``, or whose help text says markdown."""
    from karni.fields import MarkdownField

    root = _root()
    found: list[Suggestion] = []
    for model in _project_models():
        for field in model._meta.concrete_fields:
            if not isinstance(field, models.TextField) or isinstance(field, MarkdownField):
                continue
            name = str(field.name)
            help_text = str(field.help_text or "")
            if not (_MARKDOWN_NAME.search(name) or _MARKDOWN_HELP.search(help_text)):
                continue
            where = _field_suggestion(model, name, RULES["SUG002"])
            if where is None:
                continue
            path, line, no_reason = where
            found.append(
                Suggestion(
                    "SUG002",
                    _relative(path, root),
                    line,
                    f"{model.__name__}.{name} is a TextField that holds markdown: the API "
                    "publishes it as plain text, so @karni/ui shows the raw markup."
                    + (_NO_REASON if no_reason else ""),
                    f"use karni.fields.MarkdownField: {name} = MarkdownField(...), then "
                    "karni makemigrations (no data changes, it is a TextField in the database).",
                )
            )
    return found


def suggest_taxonomies() -> list[Suggestion]:
    """SUG004: three models with a many-to-many to the same tree model, none a taxonomy."""
    from karni.models import TreeModel
    from karni.taxonomy import declared_taxonomies

    root = _root()
    tagged: dict[str, list[tuple[type[models.Model], str]]] = {}
    for model in _project_models():
        try:
            declared = set(declared_taxonomies(model))
        except Exception:  # noqa: BLE001 - a malformed declaration is karni.E570's to report
            declared = set()
        for field in model._meta.many_to_many:
            target = field.related_model
            if (
                not isinstance(target, type)
                or not issubclass(target, TreeModel)
                or str(field.name) in declared
            ):
                continue
            tagged.setdefault(target._meta.label, []).append((model, str(field.name)))
    found: list[Suggestion] = []
    for label, rows in sorted(tagged.items()):
        kept: list[tuple[type[models.Model], str, Path, int, bool]] = []
        for model, name in rows:
            where = _field_suggestion(model, name, RULES["SUG004"])
            if where is not None:
                kept.append((model, name, *where))
        if len(kept) < TAXONOMY_MIN:
            continue
        model, name, path, line, _ = kept[0]
        tree = label.split(".")[1]
        names = ", ".join(f"{m.__name__}.{n}" for m, n, *_rest in kept)
        key = tree[:1].lower() + tree[1:]
        found.append(
            Suggestion(
                "SUG004",
                _relative(path, root),
                line,
                f"{len(kept)} models have a many-to-many to the tree model {tree} ({names}): "
                "each needs the same filters, facet counts, import columns and access rule."
                + (_NO_REASON if any(item[4] for item in kept) else ""),
                f"declare it once per model: class Karni: taxonomies = {{{key!r}: {label!r}}}, "
                "and drop the many-to-many (Karni adopts one you keep, for its own through model).",
            )
        )
    return found


# raw SQL with GROUP BY ---------------------------------------------------------------


def _strings(node: ast.AST, names: dict[str, str]) -> str:
    """The text of every string constant under ``node``, and of a name a constant was bound to."""
    parts: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            parts.append(child.value)
        elif isinstance(child, ast.Name) and child.id in names:
            parts.append(names[child.id])
    return " ".join(parts)


def _constant_names(tree: ast.Module) -> dict[str, str]:
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                text = _strings(node.value, {})
                if text:
                    found[target.id] = found.get(target.id, "") + " " + text
    return found


def _optout_group_by(path: Path) -> list[int]:
    """Lines of ``path`` with raw SQL that has GROUP BY and a ``karni: allow(raw-sql)`` marker."""
    from karni.agent.check import SqlVisitor

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    lines = _file_lines(path)
    names = _constant_names(tree)

    class Visitor(SqlVisitor):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[int, ast.Call]] = []

        def visit_Call(self, node: ast.Call) -> None:
            before = len(self.hits)
            super().visit_Call(node)
            if len(self.hits) > before:
                self.calls.append((node.lineno, node))

    visitor = Visitor()
    visitor.visit(tree)
    found: list[int] = []
    for lineno, call in visitor.calls:
        if not _GROUP_BY.search(_strings(call, names)):
            continue
        if marker(lines, "raw-sql", (lineno,)) is None:
            continue  # not an opt-out: the raw-sql rule reports it, or it lives in sql_allowed
        found.append(lineno)
    return found


def suggest_aggregate() -> list[Suggestion]:
    """SUG003: several raw SQL opt-outs whose SQL has GROUP BY."""
    from karni.testing._source import project_app_configs, project_sources

    root = _root()
    rule = RULES["SUG003"]
    kept: list[tuple[str, int, bool]] = []
    for config in project_app_configs():
        for path in project_sources(config):
            lines = _file_lines(path)
            for lineno in _optout_group_by(path):
                state = marker(lines, rule, (lineno, lineno - 1))
                if state == "silenced":
                    continue
                kept.append((_relative(path, root), lineno, state == "no-reason"))
    if len(kept) < AGGREGATE_MIN:
        return []
    where = ", ".join(f"{file}:{line}" for file, line, _ in kept)
    first_file, first_line, _ = kept[0]
    return [
        Suggestion(
            "SUG003",
            first_file,
            first_line,
            f"{len(kept)} raw SQL queries with GROUP BY opt out of the raw-sql rule ({where}): "
            "grouped counts and sums a resource can declare."
            + (_NO_REASON if any(item[2] for item in kept) else ""),
            "declare it on the model: class Karni: aggregate = {'group_by': [...], 'values': "
            "[...]}. The viewset then answers GET <resource>/aggregate/?group_by=..., under the "
            "list's filters and access (karni.aggregation).",
        )
    ]


# modules nothing uses -----------------------------------------------------------------


def _scan_files(root: Path) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in _SKIP_DIRS and not name.startswith(".")]
        for name in files:
            path = Path(folder) / name
            if not name.endswith(_SCAN_SUFFIXES):
                continue
            try:
                if path.stat().st_size > _MAX_SCAN_BYTES:
                    continue
                found.append((path, path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError):
                continue
    return found


def _wired_lines(manifest: Any) -> list[str]:
    """What ``karni add`` writes for the module: the lines that are not the project using it."""
    wiring = manifest.wiring
    wired = [entry.path for entry in (*wiring.middleware, *wiring.context_processors)]
    wired += [wiring.urls, wiring.settings]
    wired += [f'"{app}"' for app in wiring.apps] + [f"'{app}'" for app in wiring.apps]
    return [text.strip() for text in wired if text.strip()]


def _is_wiring(path: Path, root: Path, line: str, wired: list[str]) -> bool:
    relative = _relative(path, root)
    if relative not in ("config/settings.py", "config/urls.py"):
        return False
    stripped = line.strip().rstrip(",")
    return any(stripped == w.rstrip(",") or w in stripped for w in wired if w)


def _module_in_use(
    manifest: Any, files: list[tuple[Path, str]], root: Path, facts_modules: dict[str, Any]
) -> bool:
    tokens = [manifest.app or f"karni_{manifest.name}"]
    if manifest.provides.ui:
        tokens.append(manifest.provides.ui)
    wired = _wired_lines(manifest)
    for path, text in files:
        if not any(token in text for token in tokens):
            continue
        for line in text.splitlines():
            if any(token in line for token in tokens) and not _is_wiring(path, root, line, wired):
                return True
    known = facts_modules.get(manifest.name)
    if known and any(known["settings"][key] != known["defaults"][key] for key in known["defaults"]):
        return True
    return False


def suggest_unused_modules() -> list[Suggestion]:
    """SUG005: an added module with no import, URL or template use and no setting changed."""
    from karni import catalog
    from karni.facts import _modules

    try:
        manifests = {m.name: m for m in catalog.installed()}
    except catalog.ManifestError:
        return []
    labels = {config.name for config in apps.get_app_configs()}
    added = [m for m in manifests.values() if m.app and m.app in labels]
    if not added:
        return []
    root = _root()
    facts_modules = {item["name"]: item for item in _modules()}
    files = _scan_files(root)
    settings_path = root / "config" / "settings.py"
    settings_lines = _file_lines(settings_path)
    found: list[Suggestion] = []
    for manifest in sorted(added, key=lambda m: m.name):
        if any(manifest.name in other.requires for other in added if other is not manifest):
            continue
        if _module_in_use(manifest, files, root, facts_modules):
            continue
        quoted = (f'"{manifest.app}"', f"'{manifest.app}'")
        line = next(
            (n for n, text in enumerate(settings_lines, start=1) if any(q in text for q in quoted)),
            None,
        )
        state = (
            marker(settings_lines, RULES["SUG005"], (line, line - 1)) if line is not None else None
        )
        if state == "silenced":
            continue
        found.append(
            Suggestion(
                "SUG005",
                "config/settings.py",
                line,
                f"the module {manifest.name} is added, and nothing in the project imports it, "
                "renders its templates, includes its URLs beyond `karni add` or changes one of "
                "its settings." + (_NO_REASON if state == "no-reason" else ""),
                f"take it out with karni remove {manifest.name} (it never drops data: see "
                "`karni remove --help`), or silence this with "
                "`# karni: allow(suggest-unused-module): <reason>` on its line in "
                "config/settings.py.",
                command=f"karni remove {manifest.name}",
            )
        )
    return found


#: The detectors :func:`detect` runs, in report order.
DETECTORS: tuple[Callable[[], list[Suggestion]], ...] = (
    suggest_tree_models,
    suggest_markdown_fields,
    suggest_aggregate,
    suggest_taxonomies,
    suggest_unused_modules,
)


def detect(detectors: Iterable[Callable[[], list[Suggestion]]] | None = None) -> list[Suggestion]:
    """Every suggestion of the running project, or ``[]`` while ``KARNI_SUGGESTIONS`` is off.

    A detector that raises is skipped: a suggestion must never break a check.
    """
    if not enabled():
        return []
    found: list[Suggestion] = []
    for detector in detectors if detectors is not None else DETECTORS:
        try:
            found += detector()
        except Exception:  # noqa: BLE001 - a broken detector must not stop karni check
            continue
    return sorted(found, key=lambda s: (s.code, s.file, s.line or 0))
