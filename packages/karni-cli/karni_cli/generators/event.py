"""``karni make event <name>`` — a custom event (a Django ``Signal``) in ``<app>/events.py``.

``events.py`` is autodiscovered at startup together with ``listeners.py``
(:mod:`karni.events`); receive the event with ``karni make listener <name>
--on <event>``.
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
from karni_cli.generators.naming import require_snake
from karni_cli.generators.pysource import Import, comment, ensure_imports, replace_or_append

NAME = "event"
SUMMARY = "Add a custom event (a Django Signal) to <app>/events.py."


def plan(ws: Workspace, app: App, name: str) -> str:
    require_snake(name, "Event name")
    path = app.file("events.py")
    rel = ws.rel(path)
    line = ws.line_length
    doc = "\n".join(
        [
            comment(f"Send: {name}.send(sender=MyModel, instance=obj)", "", line, "#: "),
            comment(f"Receive: karni make listener <name> --on {name}", "", line, "#: "),
        ]
    )
    block = f"{doc}\n{name} = Signal()"
    text = ensure_imports(ws, rel, ws.read(path) or "", [Import("django.dispatch", "Signal")])
    ws.write(path, replace_or_append(ws, rel, text, name, block))
    ws.note(
        f"event: {app.module}.events.{name} (listen with: karni make listener <name> --on {name})"
    )
    return name


def command(
    name: str = typer.Argument(..., help="Event name, snake_case (e.g. order_shipped)."),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add `NAME = Signal()` to APP/events.py (autodiscovered with the listeners)."""
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), name)
    ws.commit(dry_run=dry_run)
