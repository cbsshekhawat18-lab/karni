"""``karni make listener <name> --on Model.created|updated|deleted | <event>`` — a receiver.

Writes to ``<app>/listeners.py``, which Karni autodiscovers at startup
(:mod:`karni.events`) — no ``AppConfig.ready()`` wiring.

* ``--on Event.created`` (``updated``/``deleted``; ``shop.Event.created``
  for another app's model) → ``@on_created(Event)``; soft deletes count as
  deleted. ``--queued`` → ``queued=True``: the work runs in a Celery worker
  after the transaction commits.
* ``--on order_shipped`` (or ``shop.events.order_shipped``) → a
  ``@receiver`` for a custom event from ``events.py``. ``--queued`` creates
  the task ``<app>.tasks.<name>`` and queues it on commit.
"""

from __future__ import annotations

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
from karni_cli.generators.introspect import (
    find_model,
    models_in,
    top_level_assignments,
    top_level_functions,
)
from karni_cli.generators.naming import require_snake, snake
from karni_cli.generators.pysource import Import, docstring, ensure_imports, replace_or_append
from karni_cli.project import CliError

NAME = "listener"
SUMMARY = "Add a listener to <app>/listeners.py: --on Model.created|updated|deleted or an event."

_LIFECYCLE = re.compile(
    r"^(?:(?P<app>[a-z_]\w*)\.)?(?P<model>[A-Z]\w*)\.(?P<event>created|updated|deleted)$"
)
_EVENT = re.compile(r"^(?:(?P<module>[a-z_][\w.]*)\.events\.)?(?P<event>[a-z_]\w*)$")
_ON_HELP = (
    "Model.created|Model.updated|Model.deleted (app_label.Model.event for an installed "
    "app's model, e.g. karni_payments.Payment.updated), or a custom event (order_shipped)"
)
#: The user model's label when no local app defines ``User`` (Karni's default).
_USER_MODEL = "karni_accounts.User"


def _local_app(ws: Workspace, label: str) -> App | None:
    for other in local_apps(ws):
        if label in (other.label, other.module):
            return other
    return None


def _app_named(ws: Workspace, label: str) -> App:
    found = _local_app(ws, label)
    if found is None:
        raise CliError(f"--on: no local app {label!r}.", code="C102")
    return found


def plan(ws: Workspace, app: App, name: str, *, on: str, queued: bool = False) -> None:
    require_snake(name, "Listener name")
    line = ws.line_length
    lifecycle = _LIFECYCLE.match(on)
    custom = None if lifecycle else _EVENT.match(on)
    imports: list[Import] = []
    if lifecycle:
        label, model_name, event = lifecycle["app"], lifecycle["model"], lifecycle["event"]
        owner = _local_app(ws, label) if label else app
        model = None
        if owner is not None:
            model = (
                models_in(ws, owner).get(model_name) if label else find_model(ws, owner, model_name)
            )
        # Not a local model: an installed app's (karni_payments.Payment) or the user
        # model. karni.events takes the lazy "app_label.Model" string, so no import.
        lazy = f"{label}.{model_name}" if label else (_USER_MODEL if model_name == "User" else "")
        if model is None and not lazy:
            raise CliError(
                f"--on {on}: no model {model_name} — create it first: karni make model "
                f"{model_name}, or name an installed app's model as app_label.{model_name}.{event}.",
                code="C105",
            )
        target = model.name if model is not None else f'"{lazy}"'
        annotation = model.name if model is not None else "Any"
        decorator = f"@on_{event}({target}{', queued=True' if queued else ''})"
        param = snake(model_name)
        if param == name:
            param = "instance"
        where = (
            "in a Celery worker, after commit" if queued else "inline, in the saving transaction"
        )
        lines = [
            decorator,
            f"def {name}({param}: {annotation}) -> None:",
            docstring(f"Runs after {model_name} rows are {event} — {where}.", "    ", line),
        ]
        imports.append(Import("karni.events", f"on_{event}"))
        imports.append(
            Import(model.import_module, model.name)
            if model is not None
            else Import("typing", "Any")
        )
    elif custom:
        source = _app_named(ws, custom["module"]) if custom["module"] else app
        event = custom["event"]
        events_path = source.file("events.py")
        if event not in top_level_assignments(ws, events_path):
            raise CliError(
                f"--on {on}: no event {event} in {ws.rel(events_path)} — "
                f"karni make event {event} --app {source.label}",
                code="C105",
            )
        lines = [f"@receiver({event})", f"def {name}(sender: Any, **kwargs: Any) -> None:"]
        imports += [
            Import("typing", "Any"),
            Import("django.dispatch", "receiver"),
            Import(f"{source.module}.events", event),
        ]
        if queued:
            if name not in top_level_functions(ws, app.file("tasks.py")):
                task_gen.plan(ws, app, name, announce=False)
            lines.append(
                docstring(f"Queues tasks.{name} once the transaction commits.", "    ", line)
            )
            lines.append(f"    transaction.on_commit(tasks.{name}.delay)")
            imports += [Import("django.db", "transaction"), Import(app.module, "tasks")]
        else:
            lines.append(
                docstring(f"Runs when {event} is sent — inline, in the sender.", "    ", line)
            )
    else:
        raise CliError(f"--on {on!r}: expected {_ON_HELP}.", code="C106")
    path = app.file("listeners.py")
    rel = ws.rel(path)
    text = ensure_imports(ws, rel, ws.read(path) or "", imports)
    ws.write(path, replace_or_append(ws, rel, text, name, "\n".join(lines)))
    ws.note(f"listener: {app.module}.listeners.{name} on {on} (autodiscovered at startup)")


def command(
    name: str = typer.Argument(..., help="Listener function name, snake_case."),
    on: str = typer.Option(..., "--on", help=_ON_HELP + "."),
    queued: bool = typer.Option(
        False, "--queued", help="Run the work in a Celery worker after the transaction commits."
    ),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add a listener to APP/listeners.py (autodiscovered — no AppConfig.ready wiring).

    --on Event.created|updated|deleted uses karni.events (soft deletes count
    as deleted); --on order_shipped receives a custom event from events.py.
    """
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), name, on=on, queued=queued)
    ws.commit(dry_run=dry_run)
