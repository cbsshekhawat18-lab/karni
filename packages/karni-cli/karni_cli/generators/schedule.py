"""``karni make schedule <name> --every 15m | --cron "0 3 * * *"`` — a beat schedule.

Appends ``every(...)`` / ``cron(...)`` to ``<app>/schedules.py``
(:mod:`karni.schedule`; autodiscovered into Celery beat). Without ``--task``
the schedule runs ``<app>.tasks.<name>``, created when it does not exist yet.
"""

from __future__ import annotations

import ast
import re

import typer

from karni_cli.generators import task as task_gen
from karni_cli.generators.core import (
    APP_OPTION,
    DRY_RUN_OPTION,
    FORCE_OPTION,
    App,
    Workspace,
    local_apps,
    project_workspace,
    resolve_app,
)
from karni_cli.generators.introspect import top_level_functions
from karni_cli.generators.pysource import (
    Import,
    append,
    call,
    ensure_imports,
    parse,
    pystr,
    replace_span,
    span,
)
from karni_cli.project import CliError

NAME = "schedule"
SUMMARY = "Add a beat schedule (every/cron) to <app>/schedules.py, creating the task if needed."

# Mirrors karni.schedule's own validation, so mistakes fail before any write.
_INTERVAL = re.compile(r"^\s*(?:\d+\s*[dhms]\s*)+$")
_DOTTED = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def _declared(ws: Workspace, rel: str, text: str) -> dict[str, ast.stmt]:
    """``name=`` of each top-level every()/cron() call in a schedules module."""
    found: dict[str, ast.stmt] = {}
    if not text:
        return found
    for node in parse(ws, rel, text).body:
        value = node.value if isinstance(node, ast.Expr | ast.Assign) else None
        if not isinstance(value, ast.Call):
            continue
        func = value.func
        called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if called not in {"every", "cron"}:
            continue
        for keyword in value.keywords:
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                found[str(keyword.value.value)] = node
    return found


def _app_schedules(ws: Workspace, app: App) -> dict[str, ast.stmt]:
    path = app.file("schedules.py")
    return _declared(ws, ws.rel(path), ws.read(path) or "")


def plan(
    ws: Workspace,
    app: App,
    name: str,
    *,
    every: str | None,
    cron: str | None,
    task: str | None,
) -> None:
    if not _NAME.match(name):
        raise CliError(
            f"Schedule name {name!r}: use letters, digits, _ - . : (e.g. nightly-report).",
            code="C103",
        )
    if (every is None) == (cron is None):
        raise CliError(
            'Give exactly one of --every (e.g. 15m, 1h, 1d) or --cron "0 3 * * *".', code="C004"
        )
    if every is not None and not _INTERVAL.match(every):
        raise CliError(
            f"--every {every!r}: use a number with s, m, h or d (30s, 15m, 1h30m, 1d).", code="C106"
        )
    if cron is not None and len(cron.split()) != 5:
        raise CliError(
            f"--cron {cron!r}: needs 5 fields 'minute hour day-of-month month day-of-week', "
            "e.g. '0 3 * * *' (03:00 daily).",
            code="C106",
        )
    for other in local_apps(ws):
        if other != app and name in _app_schedules(ws, other):
            raise CliError(
                f"Schedule {name!r} is already declared in {ws.rel(other.file('schedules.py'))}. "
                "Schedule names are project-wide (they become PeriodicTask names).",
                code="C107",
            )
    imports = [Import("karni.schedule", "every" if every is not None else "cron")]
    if task is not None:
        if not _DOTTED.match(task):
            raise CliError(
                f"--task {task!r}: give the dotted task name, e.g. shop.tasks.sync.", code="C106"
            )
        module, _, function = task.rpartition(".")
        if module == f"{app.module}.tasks" and function not in top_level_functions(
            ws, app.file("tasks.py")
        ):
            raise CliError(
                f"No task {function} in {ws.rel(app.file('tasks.py'))}. "
                f"Create it: karni make task {function} --app {app.label} (or drop --task).",
                code="C105",
            )
        ref = pystr(task)
    else:
        function = re.sub(r"\W", "_", name).lower()
        if function not in top_level_functions(ws, app.file("tasks.py")):
            task_gen.plan(ws, app, function, announce=False)
        ref = f"tasks.{function}"
        imports.append(Import(app.module, "tasks"))
    timing = pystr(every.strip() if every is not None else " ".join((cron or "").split()))
    statement = call(
        "every" if every is not None else "cron",
        [timing, ref, f"name={pystr(name)}"],
        "",
        ws.line_length,
    )
    path = app.file("schedules.py")
    rel = ws.rel(path)
    text = ensure_imports(ws, rel, ws.read(path) or "", imports)
    existing = _declared(ws, rel, text).get(name)
    if existing is not None:
        ws.refuse_existing(f"schedule {name!r} in {rel}")
        first, last = span(text.splitlines(), existing)
        text = replace_span(text, first, last, statement)
    else:
        text = append(text, statement)
    ws.write(path, text)
    ws.note(
        f"schedule: {name} (check with: karni schedule list  ·  run once: karni schedule run {name})"
    )


def command(
    name: str = typer.Argument(
        ..., help="Schedule name, unique in the project (e.g. nightly-report)."
    ),
    every: str | None = typer.Option(None, "--every", help="Interval: 30s, 15m, 1h, 1h30m, 1d."),
    cron: str | None = typer.Option(
        None, "--cron", help='Five-field crontab, e.g. "0 3 * * *" (03:00 daily).'
    ),
    task: str | None = typer.Option(
        None, "--task", help="Dotted task to run (default: `APP.tasks.<name>`, created if missing)."
    ),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add every(...)/cron(...) to APP/schedules.py, merged into Celery beat at startup.

    Without --task the schedule runs `APP.tasks.<name>` (dashes become
    underscores), which is created when missing.
    """
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), name, every=every, cron=cron, task=task)
    ws.commit(dry_run=dry_run)
