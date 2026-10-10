"""``karni make task <name>`` — a Celery ``@shared_task`` in ``<app>/tasks.py``.

Celery autodiscovers ``tasks`` modules (``karni.celery.create_celery_app``),
so the task is registered as ``<app>.tasks.<name>`` with no wiring.
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
from karni_cli.generators.pysource import (
    Import,
    call,
    docstring,
    ensure_imports,
    replace_or_append,
)
from karni_cli.project import CliError

NAME = "task"
SUMMARY = "Add a Celery task (@shared_task) to <app>/tasks.py; --retry N."


def plan(
    ws: Workspace, app: App, name: str, *, retry: int | None = None, announce: bool = True
) -> str:
    """Plan the task; returns its registered name (``<app>.tasks.<name>``)."""
    require_snake(name, "Task name")
    if retry is not None and retry < 1:
        raise CliError("--retry must be 1 or more.", code="C106")
    path = app.file("tasks.py")
    rel = ws.rel(path)
    line = ws.line_length
    if retry is None:
        decorator = "@shared_task"
    else:
        decorator = call(
            "@shared_task",
            ["autoretry_for=(Exception,)", "retry_backoff=True", f"max_retries={retry}"],
            "",
            line,
        )
    block = "\n".join(
        [
            decorator,
            f"def {name}() -> None:",
            docstring(f"Runs in a Celery worker: {name}.delay() queues it.", "    ", line),
            "    # Off-request writes are audit-stamped only inside",
            "    # karni.middleware.current_user(user).",
        ]
    )
    text = ensure_imports(ws, rel, ws.read(path) or "", [Import("celery", "shared_task")])
    ws.write(path, replace_or_append(ws, rel, text, name, block))
    dotted = f"{app.module}.tasks.{name}"
    if announce:
        ws.note(f"task: {dotted} — schedule it with: karni make schedule {name} --every 1h")
    else:
        ws.note(f"task: {dotted}")
    return dotted


def command(
    name: str = typer.Argument(..., help="Task function name, snake_case (e.g. send_digest)."),
    retry: int | None = typer.Option(
        None, "--retry", help="Retry up to N times on any exception (exponential backoff)."
    ),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add a Celery task `NAME` to APP/tasks.py (registered as APP.tasks.NAME)."""
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), name, retry=retry)
    ws.commit(dry_run=dry_run)
