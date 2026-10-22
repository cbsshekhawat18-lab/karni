"""``karni make app <name>`` — a local Django app, wired into ``# karni:apps``.

Replaces ``manage.py startapp``: only ``models.py`` and ``viewsets.py`` (plus
``apps.py``, ``migrations/`` and ``tests/``) — no admin.py, serializers.py or
urls.py, which Karni derives.
"""

from __future__ import annotations

import sys

import typer

from karni_cli.generators.core import (
    DRY_RUN_OPTION,
    SETTINGS,
    Workspace,
    project_workspace,
    require_settings,
)
from karni_cli.generators.naming import pascal, require_snake
from karni_cli.generators.pysource import docstring
from karni_cli.project import CliError
from karni_cli.settings_edit import MARKER, add_entry

NAME = "app"
SUMMARY = "Create a local Django app (models.py, viewsets.py) wired into # karni:apps."

#: Top-level names a project already uses, or that would shadow a dependency.
_TAKEN = frozenset(
    {"config", "frontend", "tests", "modules", "manage", "karni", "django", "rest_framework"}
)


def plan(ws: Workspace, name: str) -> str:
    """Plan the app ``name``; returns its label."""
    require_snake(name, "App name")
    if name in _TAKEN or name in sys.stdlib_module_names:
        raise CliError(
            f"App name {name!r} would shadow an existing module. Choose another.", code="C103"
        )
    if name.startswith("karni_"):
        raise CliError(
            f"App name {name!r}: karni_* names belong to Karni modules. Use "
            "`karni make module` for a reusable module, or drop the prefix.",
            code="C103",
        )
    settings = require_settings(ws)
    root = ws.path(name)
    if ws.exists(ws.path(f"{name}.py")):
        raise CliError(
            f"{name}.py exists in the project root, so an app {name}/ would clash.", code="C103"
        )
    line = ws.line_length
    files = {
        "__init__.py": "",
        "apps.py": (
            "from django.apps import AppConfig\n\n\n"
            f"class {pascal(name)}Config(AppConfig):\n"
            '    default_auto_field = "django.db.models.BigAutoField"\n'
            f'    name = "{name}"\n'
        ),
        "models.py": docstring(
            f"{name} models, each on karni.models.BaseModel: `karni make model <Name>`.", "", line
        )
        + "\n",
        "viewsets.py": docstring(
            f"{name} API: BaseViewSet subclasses, auto-routed: `karni make viewset <Model>`.",
            "",
            line,
        )
        + "\n",
        "migrations/__init__.py": "",
        "tests/__init__.py": "",
    }
    ws.create_skeleton({root / rel: content for rel, content in files.items()})
    updated = add_entry(
        settings, name, setting="INSTALLED_APPS", marker=MARKER, filename=SETTINGS.as_posix()
    )
    if updated is not None:
        ws.write(SETTINGS, updated)
    ws.note(f"next: karni make model <Name> [field:type ...] --app {name}")
    return name


def command(
    name: str = typer.Argument(..., help="App label, snake_case (e.g. events)."),
    force: bool = typer.Option(
        False, "--force", help="Create only the missing files of an existing app (keeps the rest)."
    ),
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Create a local app. It replaces `manage.py startapp`.

    Writes NAME/{__init__,apps,models,viewsets}.py, NAME/migrations/ and
    NAME/tests/, and adds NAME to the `# karni:apps` block of
    config/settings.py. No admin.py, serializers.py or urls.py: Karni derives
    them. An existing app is never truncated: --force only fills in missing
    files.
    """
    ws = project_workspace(force)
    plan(ws, name)
    ws.commit(dry_run=dry_run)
