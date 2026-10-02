"""``karni make service <name>`` — a module under ``<app>/services/``.

Services are where external calls live: rule K105 allows HTTP clients
(``requests``, ``httpx``, ``urllib.request``) only under ``services/`` and
``providers/``, so views, tasks and listeners call a service, never a client.
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
from karni_cli.generators.naming import humanize, pascal, require_snake
from karni_cli.generators.pysource import comment, docstring
from karni_cli.project import CliError

NAME = "service"
SUMMARY = "Add a service module (<app>/services/<name>.py) — the home of HTTP clients."


def plan(ws: Workspace, app: App, name: str) -> None:
    require_snake(name, "Service name")
    if ws.exists(app.file("services.py")):
        raise CliError(
            f"{ws.rel(app.file('services.py'))} exists — a services/ package would shadow it. "
            "Move it to services/__init__.py first, then re-run."
        )
    init = app.file("services", "__init__.py")
    if not ws.exists(init):
        ws.create(init, "")
    line = ws.line_length
    class_name = pascal(name) + ("" if name.endswith("service") else "Service")
    body = comment(
        "External calls (requests, httpx) belong here: rule K105 allows HTTP clients "
        "only under services/ and providers/. Views, tasks and listeners call this "
        "module, never a client directly.",
        "",
        line,
        prefix="",
    )
    module_doc = f'"""{humanize(name)} service.\n\n{body}\n"""'
    class_doc = docstring(f"{humanize(name)}: the calls this app makes to it.", "    ", line)
    ws.create(
        app.file("services", f"{name}.py"),
        f"{module_doc}\n\n\nclass {class_name}:\n{class_doc}\n",
    )
    ws.note(f"import: from {app.module}.services.{name} import {class_name}")


def command(
    name: str = typer.Argument(..., help="Service module name, snake_case (e.g. stripe_client)."),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add APP/services/NAME.py — the one place HTTP clients are allowed (K105)."""
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), name)
    ws.commit(dry_run=dry_run)
