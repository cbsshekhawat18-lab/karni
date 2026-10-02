"""``karni make viewset <Model>`` — a BaseViewSet with its mandatory ``access``.

ADR 0001 Q2.1: every viewset declares who reads and who writes. ``--access``
picks one of the common shapes; the default (``authenticated``) is printed
so it is never silent. Anything richer (``Owned(...) | HasRole(...)``,
``Where(...)``) is an edit of the generated declaration.
"""

from __future__ import annotations

import ast
import re

import typer

from karni_cli.generators.core import (
    APP_OPTION,
    DRY_RUN_OPTION,
    FORCE_OPTION,
    App,
    Workspace,
    project_workspace,
    resolve_app,
    split_csv,
)
from karni_cli.generators.introspect import ModelInfo, require_model, viewsets_file
from karni_cli.generators.naming import default_route, require_pascal
from karni_cli.generators.pysource import (
    Import,
    call,
    ensure_imports,
    parse,
    pystr,
    replace_or_append,
    tuple_literal,
)
from karni_cli.project import CliError

NAME = "viewset"
SUMMARY = "Add a BaseViewSet for a model, with its access declaration (--access)."

DEFAULT_ACCESS = "authenticated"
ACCESS_CHOICES = "authenticated|public-read|owned:<field>|staff|role:<name>"
_ROLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_PATH = re.compile(r"^[a-z_][a-z0-9_]*(__[a-z_][a-z0-9_]*)*$")


def access_declaration(spec: str, model: ModelInfo | None) -> tuple[list[str], list[str]]:
    """``(Access(...) keyword arguments, predicate names to import)`` for ``--access``."""
    kind, _, arg = spec.partition(":")
    if kind == "authenticated" and not arg:
        return ["read=Authenticated()", "write=Authenticated()"], ["Authenticated"]
    if kind == "public-read" and not arg:
        return ["read=Public()", "write=Authenticated()"], ["Authenticated", "Public"]
    if kind == "staff" and not arg:
        return ['read=HasRole("staff")', 'write=HasRole("staff")'], ["HasRole"]
    if kind == "role":
        if not _ROLE.match(arg):
            raise CliError(f"--access role:<name> needs a role (group) name, got {spec!r}.")
        role = pystr(arg)
        return [f"read=HasRole({role})", f"write=HasRole({role})"], ["HasRole"]
    if kind == "owned":
        if not _PATH.match(arg):
            raise CliError(
                "--access owned:<field> needs the relation to the user, e.g. owned:organizer "
                f'or owned:event__organizer (got {spec!r}). Owned("created_by") only when '
                "whoever created the row is its owner."
            )
        first = arg.split("__", 1)[0]
        if model is not None and not model.is_relation(first):
            raise CliError(
                f"--access {spec}: {model.name}.{first} is not a relation field. Owned() needs "
                f"a ForeignKey to the user, e.g. add owner:fk:User to {model.name} first."
            )
        path = pystr(arg)
        return [f"read=Owned({path})", f"write=Owned({path})"], ["Owned"]
    raise CliError(f"--access {spec!r}: choose one of {ACCESS_CHOICES}.")


def plan(
    ws: Workspace,
    app: App,
    model_name: str,
    *,
    access: str | None,
    search: list[str],
) -> str:
    """Plan ``<Model>ViewSet`` in the app's viewsets module; returns its route."""
    model = require_model(ws, app, model_name)
    declaration, predicates = access_declaration(access or DEFAULT_ACCESS, model)
    for name in search:
        if not model.has_field(name):
            raise CliError(f"--search {name}: {model.name} has no field {name!r}.")
    path = viewsets_file(ws, app)
    rel = ws.rel(path)
    text = ws.read(path) or ""
    class_name = f"{model.name}ViewSet"
    if text:
        for node in parse(ws, rel, text).body:
            if isinstance(node, ast.ClassDef) and node.name != class_name:
                for stmt in node.body:
                    if (
                        isinstance(stmt, ast.Assign)
                        and isinstance(stmt.value, ast.Name)
                        and stmt.value.id == model.name
                        and any(isinstance(t, ast.Name) and t.id == "model" for t in stmt.targets)
                    ):
                        raise CliError(
                            f"{rel} already routes {model.name} through {node.name} — edit "
                            "that class (or delete it first)."
                        )
    line = ws.line_length
    body = [f"class {class_name}(BaseViewSet):", f"    model = {model.name}"]
    body.append(call("access = Access", declaration, "    ", line))
    if search:
        # A tuple: a list class attribute is a mutable default (ruff RUF012).
        body.append(tuple_literal("search_fields = ", [pystr(s) for s in search], "    ", line))
    block = "\n".join(body)
    imports = [Import("karni.api", name) for name in ("Access", "BaseViewSet", *predicates)]
    imports.append(Import(model.import_module, model.name))
    text = ensure_imports(ws, rel, text, imports)
    ws.write(path, replace_or_append(ws, rel, text, class_name, block))
    shown = "Access(" + ", ".join(declaration) + ")"
    if access is None:
        ws.note(f"access: {shown} — the default; choose with --access {ACCESS_CHOICES}")
    else:
        ws.note(f"access: {shown}")
    route = default_route(model.name)
    ws.note(f"route: /api/{route}/ (auto-registered)")
    return route


def command(
    model: str = typer.Argument(..., help="Model class name (e.g. Event)."),
    access: str | None = typer.Option(
        None,
        "--access",
        help=f"Who reads/writes: {ACCESS_CHOICES}. Default: authenticated.",
    ),
    search: list[str] | None = typer.Option(
        None, "--search", help="search_fields, comma-separated or repeated (e.g. title,venue)."
    ),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add `<Model>ViewSet(BaseViewSet)` to APP/viewsets.py — CRUD at /api/<models>/.

    Declares `model = <Model>` and the mandatory `access` (ADR 0001):
    authenticated (default), public-read (anonymous reads), owned:<field>
    (rows whose <field> is the user), staff (role "staff"), role:<name>.
    """
    ws = project_workspace(force)
    target = resolve_app(ws, app)
    name = require_pascal(model.removesuffix("ViewSet"), "Model")
    plan(ws, target, name, access=access, search=split_csv(search))
    ws.commit(dry_run=dry_run)
