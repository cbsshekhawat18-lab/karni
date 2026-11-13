"""Experimental. The rules that keep the parts of a project independent (the family).

A project may hold several recipes, each one a *part* (``docs/family.md``). A part
works alone, so it must never name another part: no import of its code, no
``"crm.Deal"`` string, no URL name, template path or frontend import that
reaches into it. Parts meet through the contracts (``karni.people``,
``karni.events``, ``karni.timeline``, ``karni.preferences`` and
``karni_commerce``), which are not parts, so naming them is always allowed.

Three architecture rules, run by ``karni check`` and by ``pytest --pyargs
karni.testing.architecture``:

``part-imports-part`` (K315)
    A file of one part imports, or writes a string reference to, another
    part's app label: Python imports, ``"crm.Deal"``, ``"crm.deal:own"``,
    ``"crm:deal-list"``, ``"crm/x.html"``, ``apps.get_model("crm", ...)``, a
    migration dependency on it, a template ``{% include "crm/..." %}`` or a
    frontend import of ``frontend/src/crm/``.
``part-role-prefix`` (K316)
    A part added after the first one declares a role that is not
    ``<prefix>-<role>`` and not ``admin`` or ``customer`` (what ``karni recipes
    add`` already refuses at merge time, checked again on the built project).
``part-route`` (K316)
    A part's base route is a family page's route or another app's, or one of
    its generated pages is routed outside its base.

A project's parts are read from ``.karni/recipes/<name>/`` (the fragment each
part was added with, and its record). A project without that folder has no
parts, and all three rules pass.

Override / escape hatch: ``# karni: allow(part-imports-part): <reason>`` on the
line (or the line above), also as ``// ...`` in TypeScript and ``{# ... #}`` in
a template. The role and route rules read karni.yaml, so the fix is there.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from karni.testing._source import Violation, check_optout, project_root, relative

__all__ = [
    "FAMILY_ROLES",
    "FAMILY_ROUTES",
    "Part",
    "Reference",
    "check_part_imports",
    "check_part_roles",
    "check_part_routes",
    "installed_parts",
    "references_in",
]

#: The roles every part shares. Every other role is ``<prefix>-<role>``.
FAMILY_ROLES: Final = ("admin", "customer")
#: The routes of the family's own pages (core and commerce): no part's base may be one.
FAMILY_ROUTES: Final = frozenset(
    {
        "/",
        "/signin",
        "/account",
        "/search",
        "/inbox",
        "/settings",
        "/people",
        "/cart",
        "/checkout",
        "/orders",
    }
)

PARTS_DIR: Final = ".karni/recipes"
_FRONTEND_SUFFIXES: Final = (".ts", ".tsx", ".js", ".jsx", ".mjs")
_ROUTES_FILE: Final = "frontend/src/routes.tsx"
_GET_MODEL_CALLS: Final = {"get_model", "get_models", "get_app_config", "is_installed"}


@dataclass(frozen=True)
class Part:
    """One recipe in the project: its name and its app labels (its prefixes)."""

    name: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class Reference:
    """One place a file names another part: the line and what it names."""

    line: int
    other: str
    what: str


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _labels_of(fragment: Mapping[str, Any], record: Path) -> tuple[str, ...]:
    apps = fragment.get("apps")
    if isinstance(apps, dict) and apps:
        return tuple(str(label) for label in apps)
    # a fragment without apps (or none kept): the folders of the Python files the part wrote
    try:
        files = json.loads(record.read_text(encoding="utf-8")).get("files") or {}
    except (OSError, ValueError, AttributeError):
        return ()
    found = {
        name.split("/", 1)[0] for name in files if "/" in name and not name.startswith("frontend/")
    }
    return tuple(sorted(found))


def installed_parts(root: Path | None = None) -> list[Part]:
    """The parts of the project at ``root``, in ``app.recipes`` order (else by name)."""
    base = (root or project_root()) / PARTS_DIR
    if not base.is_dir():
        return []
    found: dict[str, Part] = {}
    for folder in sorted(path for path in base.iterdir() if path.is_dir()):
        labels = _labels_of(_load_yaml(folder / "karni.yaml"), folder / "record.json")
        if labels:
            found[folder.name] = Part(folder.name, labels)
    listed = _recipes_listed(root or project_root())
    ordered = [found[name] for name in listed if name in found]
    return ordered + [part for name, part in found.items() if name not in listed]


def _recipes_listed(root: Path) -> list[str]:
    app = _load_yaml(root / "karni.yaml").get("app")
    recipes = app.get("recipes") if isinstance(app, dict) else None
    return [str(name) for name in recipes] if isinstance(recipes, list) else []


# What one file names -------------------------------------------------------------------


def _label_patterns(label: str) -> list[tuple[re.Pattern[str], str]]:
    escaped = re.escape(label)
    return [
        (re.compile(rf"{escaped}\.[A-Z]\w*"), "a model reference"),
        (re.compile(rf"{escaped}\.(?:\*|[a-z_]\w*)(?::[\w*]+)?"), "a permission"),
        (re.compile(rf"{escaped}:[\w-]+"), "a URL name"),
        (re.compile(rf"{escaped}/[\w./-]+"), "a path"),
    ]


def _string_reference(value: str, others: Collection[str]) -> tuple[str, str] | None:
    if not value or any(char.isspace() for char in value):
        return None  # a sentence or a docstring names things in words, not by reference
    for other in others:
        if not value.startswith(other):
            continue
        for pattern, what in _label_patterns(other):
            if pattern.fullmatch(value):
                return other, f"{what} {value!r}"
    return None


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _python_references(tree: ast.Module, others: Collection[str]) -> list[Reference]:
    found: list[Reference] = []
    skipped: set[int] = set()  # docstrings
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                skipped.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in others:
                    found.append(Reference(node.lineno, root, f"imports {alias.name}"))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            root = node.module.split(".")[0]
            if root in others:
                found.append(Reference(node.lineno, root, f"imports from {node.module}"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in skipped:
                continue
            hit = _string_reference(node.value, others)
            if hit is not None:
                found.append(Reference(node.lineno, hit[0], f"writes {hit[1]}"))
        elif isinstance(node, ast.Call) and _call_name(node) in _GET_MODEL_CALLS and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and first.value in others:
                found.append(
                    Reference(node.lineno, str(first.value), f"asks for the app {first.value!r}")
                )
        elif isinstance(node, ast.Tuple) and len(node.elts) == 2:
            label, name = node.elts
            if (
                isinstance(label, ast.Constant)
                and label.value in others
                and isinstance(name, ast.Constant)
                and isinstance(name.value, str)
                and re.match(r"\d{4}_", name.value)
            ):
                found.append(
                    Reference(node.lineno, str(label.value), f"depends on its migration {name.value}")
                )
    return found


_TEMPLATE_TAG = re.compile(r"""\{%-?\s*(?:url|include|extends)\s+['"]([\w-]+)[:/]""")
_IMPORT_SPEC = re.compile(r"""(?:from\s+|import\s*\(?\s*|import\s+|require\(\s*)['"]([^'"]+)['"]""")


def _template_references(text: str, others: Collection[str]) -> list[Reference]:
    found: list[Reference] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _TEMPLATE_TAG.finditer(line):
            if match.group(1) in others:
                found.append(Reference(lineno, match.group(1), f"uses {match.group(0).strip()}"))
    return found


def _frontend_references(text: str, others: Collection[str]) -> list[Reference]:
    found: list[Reference] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _IMPORT_SPEC.finditer(line):
            spec = match.group(1)
            if not spec.startswith((".", "@/", "~/", "src/", "/src/")):
                continue  # a package: the contracts (@karni/ui) and libraries are fine
            segments = {s for s in spec.split("/") if s not in {"", ".", "..", "@", "~", "src"}}
            for other in others:
                if other in segments:
                    found.append(Reference(lineno, other, f"imports {spec}"))
    return found


def references_in(path: Path, others: Collection[str]) -> list[Reference]:
    """Where the file at ``path`` names one of the app labels ``others`` (a pure function).

    A Python file is read for imports and string references, a template for its
    ``url``, ``include`` and ``extends`` tags, a TypeScript or JavaScript file for
    its relative and alias imports. Any other file has no references.
    """
    if not others:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if path.suffix == ".py":
        try:
            return _python_references(ast.parse(text), others)
        except (SyntaxError, ValueError):
            return []
    if path.suffix in _FRONTEND_SUFFIXES:
        return _frontend_references(text, others)
    if path.suffix in {".html", ".txt", ".xml", ".md"} or path.suffix == "":
        return _template_references(text, others)
    return []


def _part_files(root: Path, label: str) -> Iterable[Path]:
    app = root / label
    if app.is_dir():
        for path in sorted(app.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                yield path
    frontend = root / "frontend" / "src" / label
    if frontend.is_dir():
        for path in sorted(frontend.rglob("*")):
            if path.is_file() and path.suffix in _FRONTEND_SUFFIXES:
                yield path


def check_part_imports(root: Path | None = None) -> list[Violation]:
    """``part-imports-part`` (K315): a part naming another part."""
    base = root or project_root()
    parts = installed_parts(base)
    if len(parts) < 2:
        return []
    labels = {label for part in parts for label in part.labels}
    violations: list[Violation] = []
    for part in parts:
        mine = set(part.labels)
        others = sorted(labels - mine)
        for label in part.labels:
            for path in _part_files(base, label):
                for ref in references_in(path, others):
                    owner = next((p.name for p in parts if ref.other in p.labels), ref.other)
                    violations += check_optout(
                        path,
                        "part-imports-part",
                        [ref.line, ref.line - 1],
                        Violation(
                            rule="part-imports-part",
                            location=f"{_where(path, base)}:{ref.line}",
                            message=(
                                f"the {part.name} part {ref.what}, which belongs to the "
                                f"{owner} part"
                            ),
                            hint=(
                                "a part works alone: use a contract (karni.people, karni.events, "
                                "karni.timeline, karni.preferences) or a connection in "
                                f"{label}/connections.py, or opt out with the reason"
                            ),
                        ),
                    )
    return violations


def _where(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return relative(path)


# roles and routes ----------------------------------------------------------------------


def _role_owner(slug: str, role: object, parts: list[Part], base: Path) -> Part | None:
    """The part a role in karni.yaml belongs to: the one whose fragment declared it, else the one
    its grants name alone (a role renamed since the merge keeps its grants)."""
    for part in parts:
        fragment = _load_yaml(base / PARTS_DIR / part.name / "karni.yaml").get("roles")
        if isinstance(fragment, dict) and slug in fragment:
            return part
    grants = role.get("grants") if isinstance(role, dict) else None
    patterns = [str(pattern) for pattern in grants] if isinstance(grants, dict) else []
    if not patterns:
        return None
    owners = {
        part.name: part
        for part in parts
        for pattern in patterns
        if any(pattern.startswith(f"{label}.") for label in part.labels)
    }
    only = all(
        any(pattern.startswith(f"{label}.") for part in parts for label in part.labels)
        for pattern in patterns
    )
    return next(iter(owners.values())) if len(owners) == 1 and only else None


def check_part_roles(root: Path | None = None) -> list[Violation]:
    """``part-role-prefix`` (K316): a part after the first holding a role without its prefix.

    A role belongs to the part whose fragment declared it, or, when it was renamed since, to
    the one part its grants name alone. The first part keeps its roles as its recipe wrote them.
    """
    base = root or project_root()
    parts = installed_parts(base)
    if len(parts) < 2:
        return []
    current = _load_yaml(base / "karni.yaml").get("roles")
    violations: list[Violation] = []
    for slug, role in (current if isinstance(current, dict) else {}).items():
        slug = str(slug)
        if slug in FAMILY_ROLES:
            continue
        part = _role_owner(slug, role, parts, base)
        if part is None or part is parts[0]:
            continue
        if any(slug.startswith(f"{label}-") for label in part.labels):
            continue
        violations.append(
            Violation(
                rule="part-role-prefix",
                location=f"karni.yaml: roles.{slug}",
                message=(
                    f"the {part.name} part's role {slug} is not named <prefix>-<role> "
                    f"(its app label {', '.join(part.labels)} first), and is not "
                    f"{' or '.join(FAMILY_ROLES)}"
                ),
                hint=(
                    f"rename it {part.labels[0]}-{slug} in karni.yaml and in every "
                    f"role:{slug} that names it, then karni build"
                ),
            )
        )
    return violations


def _pascal(name: str) -> str:
    return "".join(word[:1].upper() + word[1:] for word in re.split(r"[-_]", name) if word)


def _components(entity: str) -> set[str]:
    from karni.api.routers import kebab, pluralize

    names = (pluralize(kebab(entity)), f"{kebab(entity)}-detail", f"{kebab(entity)}-form")
    return {f"{_pascal(name)}Page" for name in names}


_ROUTE_LINE = re.compile(r"""path:\s*["']([^"']+)["'][^\n]*?component:\s*(\w+)""")


def check_part_routes(root: Path | None = None) -> list[Violation]:
    """``part-route`` (K316): a part's base is a family or another app's route, or a page strays."""
    base = root or project_root()
    parts = installed_parts(base)
    if not parts:
        return []
    spec = _load_yaml(base / "karni.yaml")
    apps = spec.get("apps") if isinstance(spec.get("apps"), dict) else {}
    bases: dict[str, str] = {}
    for label, app in apps.items():
        route = app.get("route") if isinstance(app, dict) else None
        bases[str(label)] = str(route) if route else f"/{label}"
    violations: list[Violation] = []
    owners: dict[str, list[str]] = {}
    for label, route in bases.items():
        owners.setdefault(route, []).append(label)
    for part in parts:
        for label in part.labels:
            route = bases.get(label)
            if route is None:
                continue
            problem = ""
            if route in FAMILY_ROUTES:
                problem = f"is {route}, a family page's route"
            elif len(owners[route]) > 1:
                other = next(name for name in owners[route] if name != label)
                problem = f"is {route}, where the app {other} has its pages"
            elif not route.startswith("/"):
                problem = f"is {route!r}, which does not start with /"
            if problem:
                violations.append(
                    Violation(
                        rule="part-route",
                        location=f"karni.yaml: apps.{label}.route",
                        message=f"the {part.name} part's base route {problem}",
                        hint=f"give {label} its own base (route: /{label}), then karni build",
                    )
                )
    violations += _stray_pages(base, parts, apps, bases)
    return violations


def _stray_pages(
    root: Path, parts: list[Part], apps: Mapping[Any, Any], bases: Mapping[str, str]
) -> list[Violation]:
    routes = root / _ROUTES_FILE
    if not routes.is_file():
        return []
    owned: dict[str, str] = {}  # component -> label, for components only one app can own
    clash: set[str] = set()
    for part in parts:
        for label in part.labels:
            app = apps.get(label)
            entities = app.get("entities") if isinstance(app, dict) else None
            for entity in entities if isinstance(entities, dict) else {}:
                for component in _components(str(entity)):
                    if owned.setdefault(component, label) != label:
                        clash.add(component)
    text = routes.read_text(encoding="utf-8")
    violations: list[Violation] = []
    for match in _ROUTE_LINE.finditer(text):
        path, component = match.group(1), match.group(2)
        label = owned.get(component)
        if label is None or component in clash or label not in bases:
            continue
        home = bases[label].rstrip("/")
        if path == home or path.startswith(f"{home}/"):
            continue
        violations.append(
            Violation(
                rule="part-route",
                location=f"{_ROUTES_FILE}:{text[: match.start()].count(chr(10)) + 1}",
                message=f"the page {component} of the {label} app is routed at {path}, outside "
                f"its base {home}",
                hint=f"route it under {home}/ (apps.{label}.route in karni.yaml, then karni build)",
            )
        )
    return violations
