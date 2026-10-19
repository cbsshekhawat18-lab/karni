"""``karni make test <Model>`` — the resource's API test: full CRUD surface plus isolation.

Writes ``<app>/tests/test_<model>.py`` with a :class:`karni.testing.APITestCase`
that calls ``assert_crud`` (list, retrieve, create, update, delete, the
promised denials, pagination, filtering and the OpenAPI contract, in one
call) and — when the viewset's ``access`` reads through ``Owned(...)``, or
through ``Granted()`` with a role whose grant is ``own`` / ``related`` —
``assert_isolated`` (another scope's rows are out of reach). The role is
``--role``, else the first ``HasRole("...")`` the viewset declares, else for
``Granted()`` the first role in ``KARNI_ROLES`` (the shipped ``user`` when
the project declares none) whose grants reach the model, else any signed-in
user. The model needs a viewset first (``karni make viewset``).
"""

from __future__ import annotations

import typer

from karni_cli.generators.core import (
    APP_OPTION,
    DRY_RUN_OPTION,
    FORCE_OPTION,
    App,
    Workspace,
    project_workspace,
    resolve_app,
)
from karni_cli.generators.introspect import (
    ModelInfo,
    declared_roles,
    grant_scopes,
    granted_reads,
    owned_paths,
    require_model,
    role_names,
    viewset_for,
    viewset_module,
)
from karni_cli.generators.naming import require_pascal, snake
from karni_cli.generators.pysource import Import, docstring, ensure_imports, pystr
from karni_cli.project import CliError

NAME = "test"
SUMMARY = "Add <app>/tests/test_<model>.py: assert_crud + the isolation check for a resource."


def render(
    ws: Workspace, model: str, viewset: str, module: str, role: str | None, isolation: bool
) -> str:
    """The test module's text (ruff-clean in the project's layout)."""
    rel = "tests/test.py"
    line = ws.line_length
    role_arg = f", {pystr(role)}" if role else ""
    lines = [
        docstring(
            f"The {model} API: CRUD, access" + (" and isolation" if isolation else "") + ".",
            "",
            line,
        ),
        "",
        "",
        f"class {model}APITests(APITestCase):",
        "    def test_crud(self) -> None:",
        f"        self.assert_crud({viewset}{role_arg})",
    ]
    if isolation:
        lines += [
            "",
            "    def test_owners_cannot_reach_each_others_rows(self) -> None:",
            f"        self.assert_isolated({viewset}{role_arg})",
        ]
    text = "\n".join(lines) + "\n"
    return ensure_imports(
        ws, rel, text, [Import("karni.testing", "APITestCase"), Import(module, viewset)]
    )


def _scoped(scope: str | None) -> bool:
    return scope is not None and (scope == "own" or scope.startswith("related:"))


def granted_role(ws: Workspace, model: ModelInfo, role: str | None) -> tuple[str | None, bool]:
    """``(role, isolates)`` for a ``Granted()`` viewset of ``model``.

    ``role`` when given; else the first role in ``KARNI_ROLES`` whose grant
    for the model's ``view`` permission is ``own`` / ``related`` (so the
    isolation check applies), else the first whose grants reach it at all.
    ``isolates`` says whether that role's grant partitions the rows.
    """
    key = f"{model.app.label}.{model.name.lower()}:view"
    scopes = grant_scopes(declared_roles(ws), key)
    if role is not None:
        return role, _scoped(scopes.get(role))
    for slug, scope in scopes.items():
        if _scoped(scope):
            return slug, True
    if scopes:
        return next(iter(scopes)), False
    return None, False


def plan(ws: Workspace, app: App, model_name: str, *, role: str | None = None) -> str:
    """Plan the test module for ``model_name``; returns its path relative to the project."""
    model = require_model(ws, app, require_pascal(model_name, "Model"))
    found = viewset_for(ws, model.app, model.name)
    if found is None:
        raise CliError(
            f"No viewset routes {model.name} — create it first: karni make viewset "
            f"{model.name} --app {model.app.label} (the test drives the resource's URLs).",
            code="C105",
        )
    path, cls = found
    roles = role_names(cls)
    chosen = role if role is not None else (roles[0] if roles else None)
    owned = bool(owned_paths(cls))
    granted = not owned and granted_reads(cls)
    how = " + owner isolation" if owned else ""
    if granted and chosen is None or granted and role is not None:
        chosen, scoped = granted_role(ws, model, role)
        how = " + grant isolation" if scoped else ""
        if chosen is None:
            ws.note(
                f"no role in KARNI_ROLES grants {model.app.label}.{model.name.lower()}:view; "
                "as any signed-in user the test is refused everything — pass --role"
            )
    module = viewset_module(ws, model.app, path)
    tests = model.app.file("tests")
    init = tests / "__init__.py"
    if not ws.exists(init):
        ws.create(init, "")
    target = tests / f"test_{snake(model.name)}.py"
    ws.create(target, render(ws, model.name, cls.name, module, chosen, bool(how)))
    who = f"role {chosen!r}" if chosen else "any signed-in user"
    ws.note(f"test: {cls.name} as {who}{how}")
    ws.note(f"run: karni test {ws.rel(target)}")
    return ws.rel(target)


def command(
    model: str = typer.Argument(..., help="Model class name (e.g. Event); it needs a viewset."),
    role: str | None = typer.Option(
        None,
        "--role",
        help="The role the test acts as. Default: the first HasRole the viewset declares; "
        "for Granted() the first KARNI_ROLES role whose grant reaches the model (own/related "
        "first); else any signed-in user.",
    ),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add APP/tests/test_<model>.py — the resource's whole API surface in a few lines.

    One APITestCase: `assert_crud` checks list, retrieve, create, update,
    delete, the denials the access declaration promises, pagination,
    filtering and the OpenAPI contract; `assert_isolated` (when reads are
    Owned, or Granted() with an own/related grant) checks another scope's
    rows are out of reach on every surface. Run it with `karni test`.
    """
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), model, role=role)
    ws.commit(dry_run=dry_run)
