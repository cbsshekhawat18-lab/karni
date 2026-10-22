"""``karni make command <name>`` — a management command in ``<app>/management/commands/``.

Run it with ``karni manage <name>`` (through the project interpreter).
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
from karni_cli.generators.naming import humanize, require_snake
from karni_cli.generators.pysource import pystr
from karni_cli.project import CliError

NAME = "command"
SUMMARY = "Add a management command (<app>/management/commands/<name>.py)."

#: Django's and Karni's own commands: an app command of the same name is shadowed.
BUILTIN = frozenset(
    {
        "changepassword",
        "check",
        "clearsessions",
        "collectstatic",
        "createsuperuser",
        "dbshell",
        "diffsettings",
        "dumpdata",
        "flush",
        "inspectdb",
        "karni_check",
        "karni_context",
        "karni_routes",
        "karni_schedules",
        "loaddata",
        "makemigrations",
        "migrate",
        "runserver",
        "sendtestemail",
        "shell",
        "showmigrations",
        "spectacular",
        "sqlflush",
        "sqlmigrate",
        "sqlsequencereset",
        "squashmigrations",
        "startapp",
        "startproject",
        "test",
        "testserver",
    }
)


def plan(ws: Workspace, app: App, name: str) -> None:
    require_snake(name, "Command name")
    if name in BUILTIN:
        raise CliError(
            f"`{name}` is a Django/Karni command, so an app command of that name would be "
            "shadowed. Choose another name.",
            code="C103",
        )
    for package in ("management", "management/commands"):
        init = app.file(*package.split("/"), "__init__.py")
        if not ws.exists(init):
            ws.create(init, "")
    help_text = pystr(f"{humanize(name)}.")
    done = pystr(f"{name}: done")
    ws.create(
        app.file("management", "commands", f"{name}.py"),
        "from typing import Any\n\n"
        "from django.core.management.base import BaseCommand\n\n\n"
        "class Command(BaseCommand):\n"
        f"    help = {help_text}\n\n"
        "    def handle(self, *args: Any, **options: Any) -> None:\n"
        f"        self.stdout.write(self.style.SUCCESS({done}))\n",
    )
    ws.note(f"run: karni manage {name}")


def command(
    name: str = typer.Argument(..., help="Command name, snake_case (e.g. send_reminders)."),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add a management command NAME to APP (run it with `karni manage NAME`)."""
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), name)
    ws.commit(dry_run=dry_run)
