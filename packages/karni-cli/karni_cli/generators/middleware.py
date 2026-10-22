"""``karni make middleware <Name>`` — a middleware class, wired into settings.

The class goes to ``<app>/middleware.py``; its dotted path is added to the
``# karni:middleware`` block of config/settings.py (``MIDDLEWARE += [...]``,
so it runs after Karni's stack). A settings file without that block gets the
exact line to add instead.
"""

from __future__ import annotations

import typer

from karni_cli.generators.core import (
    APP_OPTION,
    DRY_RUN_OPTION,
    FORCE_OPTION,
    SETTINGS,
    App,
    Workspace,
    project_workspace,
    resolve_app,
)
from karni_cli.generators.naming import require_pascal
from karni_cli.generators.pysource import Import, ensure_imports, replace_or_append
from karni_cli.project import CliError
from karni_cli.settings_edit import MIDDLEWARE_MARKER, add_entry

NAME = "middleware"
SUMMARY = "Add a middleware class to <app>/middleware.py, wired via # karni:middleware."


def plan(ws: Workspace, app: App, name: str) -> str:
    base = require_pascal(name, "Middleware name")
    class_name = base if base.endswith("Middleware") else f"{base}Middleware"
    path = app.file("middleware.py")
    rel = ws.rel(path)
    block = "\n".join(
        [
            f"class {class_name}:",
            "    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:",
            "        self.get_response = get_response",
            "",
            "    def __call__(self, request: HttpRequest) -> HttpResponse:",
            "        # Runs before the view (and the middleware after this one).",
            "        response = self.get_response(request)",
            "        # Runs after the view.",
            "        return response",
        ]
    )
    imports = [
        Import("collections.abc", "Callable"),
        Import("django.http", "HttpRequest"),
        Import("django.http", "HttpResponse"),
    ]
    text = ensure_imports(ws, rel, ws.read(path) or "", imports)
    ws.write(path, replace_or_append(ws, rel, text, class_name, block))
    dotted = f"{app.module}.middleware.{class_name}"
    settings = ws.read(SETTINGS)
    try:
        if settings is None:
            raise CliError(f"{SETTINGS.as_posix()} not found", code="C001")
        updated = add_entry(
            settings,
            dotted,
            setting="MIDDLEWARE",
            marker=MIDDLEWARE_MARKER,
            filename=SETTINGS.as_posix(),
        )
    except CliError:
        ws.note(
            f"wire it yourself: add {dotted!r} to MIDDLEWARE in {SETTINGS.as_posix()} "
            f"(projects scaffolded before `{MIDDLEWARE_MARKER}` have no marker block)."
        )
    else:
        if updated is not None:
            ws.write(SETTINGS, updated)
        ws.note(f"middleware: {dotted} (last in MIDDLEWARE — move it if order matters)")
    return dotted


def command(
    name: str = typer.Argument(..., help="Class name, PascalCase (Middleware suffix added)."),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add a middleware class to APP/middleware.py and wire it into MIDDLEWARE.

    Wiring goes through the `# karni:middleware` block of config/settings.py
    (appended after Karni's middleware). Without that block the command
    prints the line to add.
    """
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), name)
    ws.commit(dry_run=dry_run)
