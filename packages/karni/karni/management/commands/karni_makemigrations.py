"""``manage.py karni_makemigrations [app ...] [--renames JSON]`` (experimental), for karni build.

Django's ``makemigrations``, run without questions, with the two answers it
cannot give alone:

* **Renames.** ``--renames`` is ``{"models": [[app, old, new], ...],
  "fields": [[app, model, old, new], ...]}``, ``model`` being the model's
  name after any rename. They are written first, as one migration per app of
  ``RenameModel`` and ``RenameField`` operations, so a renamed table or
  column keeps its rows, also when its type changes in the same build.
  Django's own detection asks about a rename only when nothing else changed.
* **A required field added to an empty table.** Django asks for a one-off
  value to fill the rows of a new column that cannot be empty. A table
  without rows has nothing to fill, so the column is added without one. A
  table with rows stops the command the way ``makemigrations --no-input``
  does: give the field a default, or add it as optional first.

Override / escape hatch: :class:`EmptyTableQuestioner` is importable, and
Django's own ``makemigrations`` still works on every project.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.apps import apps
from django.core.management.base import CommandError, CommandParser
from django.core.management.commands import makemigrations as django_makemigrations
from django.db import DatabaseError, migrations, router
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.questioner import NonInteractiveMigrationQuestioner
from django.db.migrations.writer import MigrationWriter


class EmptyTableQuestioner(NonInteractiveMigrationQuestioner):
    """Experimental. Adds a required field to a model whose table holds no row, without a value."""

    def ask_not_null_addition(self, field_name: str, model_name: str) -> Any:
        model = _model(self.specified_apps, model_name)
        if model is not None and _empty(model):
            return None
        return super().ask_not_null_addition(field_name, model_name)


def _model(labels: Any, model_name: str) -> Any:
    for config in apps.get_app_configs():
        if labels and config.label not in labels:
            continue
        for model in config.get_models():
            if model._meta.model_name == model_name:
                return model
    return None


def _empty(model: Any) -> bool:
    alias = router.db_for_write(model)
    try:
        return not model._base_manager.using(alias).exists()
    except DatabaseError:  # a table not there yet (renamed in the same build): ask as Django does
        return False


def write_renames(renames: dict[str, Any]) -> list[str]:
    """Experimental. Write the rename migrations ``renames`` asks for; returns their paths."""
    loader = MigrationLoader(None, ignore_no_migrations=True)
    by_app: dict[str, list[Any]] = {}
    for app_label, old, new in renames.get("models") or []:
        by_app.setdefault(app_label, []).append(migrations.RenameModel(old, new))
    for app_label, model, old, new in renames.get("fields") or []:
        by_app.setdefault(app_label, []).append(
            migrations.RenameField(str(model).lower(), old, new)
        )
    written = []
    for app_label, operations in by_app.items():
        leaves = loader.graph.leaf_nodes(app_label)
        if len(leaves) != 1:
            raise CommandError(
                f"{app_label} has {len(leaves)} latest migrations, so the renames have no single "
                "place to go. Run manage.py makemigrations --merge first."
            )
        number = (MigrationAutodetector.parse_number(leaves[0][1]) or 0) + 1
        migration = migrations.Migration(f"{number:04d}_karni_renames", app_label)
        migration.dependencies = [leaves[0]]
        migration.operations = operations
        writer = MigrationWriter(migration)
        Path(writer.path).write_text(writer.as_string(), encoding="utf-8")
        written.append(writer.path)
    return written


class Command(django_makemigrations.Command):
    help = (
        "Experimental. makemigrations for karni build: explicit renames first, and a required "
        "field added to an empty table without a one-off value. Never asks a question."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        super().add_arguments(parser)
        parser.add_argument(
            "--renames",
            default="{}",
            help='JSON: {"models": [[app, old, new]], "fields": [[app, model, old, new]]}.',
        )

    def handle(self, *app_labels: str, **options: Any) -> None:
        try:
            renames = json.loads(options.pop("renames") or "{}")
        except json.JSONDecodeError as exc:
            raise CommandError(f"--renames is not JSON: {exc}") from None
        if not isinstance(renames, dict):
            raise CommandError("--renames must be a JSON object with models and fields.")
        written = write_renames(renames)
        options["interactive"] = False
        chosen = django_makemigrations.NonInteractiveMigrationQuestioner
        django_makemigrations.NonInteractiveMigrationQuestioner = EmptyTableQuestioner  # type: ignore[misc]
        try:
            super().handle(*app_labels, **options)
        except BaseException:
            # all or nothing: a rename migration without the rest would be applied twice
            for path in written:
                Path(path).unlink(missing_ok=True)
            raise
        finally:
            django_makemigrations.NonInteractiveMigrationQuestioner = chosen  # type: ignore[misc]
        for path in written:
            self.stdout.write(f"Renames written: {path}")
