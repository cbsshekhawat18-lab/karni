"""Static (AST) facts about a project's apps — what already exists, without Django."""

from __future__ import annotations

import ast
import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from karni_cli.generators.core import SETTINGS, App, Workspace, local_apps
from karni_cli.generators.pysource import parse
from karni_cli.project import CliError

#: karni.conf.base's default KARNI_ROLES, mirrored (the CLI runs without karni):
#: staff holds everything, user and customer their own rows.
SHIPPED_ROLES: dict[str, dict[str, Any]] = {
    "staff": {"grants": {"*": "all"}},
    "user": {"grants": {"*": "own"}},
    "customer": {"grants": {"*": "own"}},
}

_RELATION_CALLS = frozenset({"ForeignKey", "OneToOneField", "ManyToManyField"})
_AUDIT_BASES = frozenset({"BaseModel", "AuditedModel"})


@dataclass(frozen=True)
class ModelInfo:
    app: App
    name: str
    path: Path
    #: field name -> the called class name (``CharField``, ``ForeignKey`` …)
    fields: dict[str, str]
    bases: frozenset[str]

    @property
    def import_module(self) -> str:
        return f"{self.app.module}.models"

    def is_relation(self, name: str) -> bool:
        if name in {"created_by", "updated_by"}:
            return bool(self.bases & _AUDIT_BASES)
        return self.fields.get(name) in _RELATION_CALLS

    def has_field(self, name: str) -> bool:
        if name in {"id", "pk", "created_at", "updated_at", "created_by", "updated_by"}:
            return True
        return name in self.fields


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            return func.attr
        if isinstance(func, ast.Name):
            return func.id
    return ""


def class_fields(cls: ast.ClassDef) -> dict[str, str]:
    """``name = models.X(...)`` assignments in a class body → ``{name: "X"}``."""
    found: dict[str, str] = {}
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            called = _call_name(stmt.value)
            if isinstance(target, ast.Name) and (
                called.endswith("Field") or called in _RELATION_CALLS
            ):
                found[target.id] = called
    return found


def _bases(cls: ast.ClassDef) -> frozenset[str]:
    names: set[str] = set()
    for base in cls.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return frozenset(names)


def models_file(ws: Workspace, app: App) -> Path:
    """``<app>/models.py``; a ``models/`` package is an unsupported layout."""
    path = app.file("models.py")
    if not ws.exists(path) and ws.is_dir(app.file("models")):
        raise CliError(
            f"{ws.rel(app.file('models'))}/ is a package, but karni make writes "
            f"{ws.rel(path)}. Add the class to the package yourself (and re-export it "
            "from models/__init__.py).",
            code="C107",
        )
    return path


def models_in(ws: Workspace, app: App) -> dict[str, ModelInfo]:
    path = models_file(ws, app)
    text = ws.read(path)
    if text is None:
        return {}
    tree = parse(ws, ws.rel(path), text)
    found: dict[str, ModelInfo] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            found[node.name] = ModelInfo(app, node.name, path, class_fields(node), _bases(node))
    return found


def find_model(ws: Workspace, app: App, name: str) -> ModelInfo | None:
    """``name`` in ``app``'s models, else in exactly one other local app."""
    own = models_in(ws, app).get(name)
    if own is not None:
        return own
    others = [
        info
        for other in local_apps(ws)
        if other != app
        for info in [models_in(ws, other).get(name)]
        if info is not None
    ]
    return others[0] if len(others) == 1 else None


def require_model(ws: Workspace, app: App, name: str) -> ModelInfo:
    info = find_model(ws, app, name)
    if info is None:
        raise CliError(
            f"No model {name} in {ws.rel(models_file(ws, app))}. Create it first: "
            f"karni make model {name} --app {app.label}",
            code="C105",
        )
    return info


def viewsets_file(ws: Workspace, app: App) -> Path:
    """``<app>/viewsets.py``, or ``<app>/api/viewsets.py`` when only that exists."""
    plain = app.file("viewsets.py")
    nested = app.file("api", "viewsets.py")
    if not ws.exists(plain) and ws.exists(nested):
        return nested
    return plain


def viewset_for(ws: Workspace, app: App, model: str) -> tuple[Path, ast.ClassDef] | None:
    """The class in the app's viewsets module whose body says ``model = <model>``."""
    path = viewsets_file(ws, app)
    text = ws.read(path)
    if text is None:
        return None
    for node in parse(ws, ws.rel(path), text).body:
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "model" for t in stmt.targets)
                and isinstance(stmt.value, ast.Name)
                and stmt.value.id == model
            ):
                return path, node
    return None


def owned_paths(cls: ast.ClassDef) -> list[str]:
    """String arguments of every ``Owned("...")`` call in the class body."""
    found: list[str] = []
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Call)
            and _call_name(node) == "Owned"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.append(node.args[0].value)
    return found


def top_level_functions(ws: Workspace, path: Path) -> set[str]:
    text = ws.read(path)
    if text is None:
        return set()
    tree = parse(ws, ws.rel(path), text)
    return {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def top_level_assignments(ws: Workspace, path: Path) -> set[str]:
    text = ws.read(path)
    if text is None:
        return set()
    names: set[str] = set()
    for node in parse(ws, ws.rel(path), text).body:
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def role_names(cls: ast.ClassDef) -> list[str]:
    """String arguments of every ``HasRole("...")`` call in the class body, in order."""
    found: list[str] = []
    for node in ast.walk(cls):
        if isinstance(node, ast.Call) and _call_name(node) == "HasRole":
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value not in found
                ):
                    found.append(arg.value)
    return found


def writing_roles(cls: ast.ClassDef) -> list[str]:
    """The ``HasRole("...")`` names a test must hold to write, in order of preference.

    The roles named in the ``write=`` keyword of ``Access(...)`` come first,
    then those in ``create=``, then every other ``HasRole`` in the class
    body. A test acting as the first of them exercises real creates,
    updates and deletes, where a role named only in ``read=`` (say, a
    ``viewer``) would only confirm the refusals.
    """
    found: list[str] = []
    for slot in ("write", "create"):
        for node in ast.walk(cls):
            if not (isinstance(node, ast.Call) and _call_name(node) == "Access"):
                continue
            for keyword in node.keywords:
                if keyword.arg == slot:
                    found += [name for name in _role_names_in(keyword.value) if name not in found]
    return found + [name for name in role_names(cls) if name not in found]


def _role_names_in(node: ast.AST) -> list[str]:
    found: list[str] = []
    for call in ast.walk(node):
        if isinstance(call, ast.Call) and _call_name(call) == "HasRole":
            for arg in call.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value not in found
                ):
                    found.append(arg.value)
    return found


def granted_reads(cls: ast.ClassDef) -> bool:
    """Whether the class body calls ``Granted()`` — the roles' grants decide its rows."""
    return any(
        isinstance(node, ast.Call) and _call_name(node) == "Granted" for node in ast.walk(cls)
    )


def declared_roles(ws: Workspace) -> dict[str, dict[str, Any]]:
    """``KARNI_ROLES`` from config/settings.py when it is a literal, else the shipped default."""
    text = ws.read(SETTINGS)
    if text is None:
        return dict(SHIPPED_ROLES)
    for node in parse(ws, ws.rel(SETTINGS), text).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "KARNI_ROLES" for target in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return {}  # computed at runtime: unknown here
            return value if isinstance(value, dict) else {}
    return dict(SHIPPED_ROLES)


def grant_scopes(roles: dict[str, dict[str, Any]], key: str) -> dict[str, str]:
    """Role slug → the scope its grants give ``key`` (``app.model:action``); later patterns win."""
    found: dict[str, str] = {}
    for slug, spec in roles.items():
        grants = spec.get("grants") if isinstance(spec, dict) else None
        if not isinstance(grants, dict):
            continue
        scope = None
        for pattern, value in grants.items():
            glob = "*:*" if pattern == "*" else str(pattern)
            if fnmatch.fnmatchcase(key, glob):
                scope = str(value)
        if scope is not None:
            found[slug] = scope
    return found


def viewset_module(ws: Workspace, app: App, path: Path) -> str:
    """The dotted module of a viewsets file of ``app`` (``events.viewsets``)."""
    rel = path.relative_to(app.path).with_suffix("")
    return ".".join([app.module, *rel.parts])
