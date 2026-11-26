"""``makemigrations`` that re-creates a generated field whose definition changed (experimental).

Django cannot alter a ``GeneratedField`` in place: changing its expression,
its output field or ``db_persist`` makes ``migrate`` fail with "Modifying
GeneratedFields is not supported". ``SearchField`` is one, so adding a source
to ``SearchField(sources=[...])`` wrote an ``AlterField`` that could not run.

:class:`KarniAutodetector` writes ``RemoveField`` then ``AddField`` for such a
field instead. The column holds nothing a database cannot compute again, so
nothing is lost. Everything that is attached to the column goes with it: an
index or a constraint that names the field is removed first and added back
after (a GIN index on a ``SearchField``, which the database drops with the
column), and so is a ``unique_together`` entry that names it (SQLite refuses
to drop the column under it, PostgreSQL drops it with the column and nothing
made it again). A change that is not a change to the column (``verbose_name``,
``help_text``) stays an ``AlterField``, and the column is not touched.

``karni.management.commands.makemigrations`` runs it for ``makemigrations``
and ``karni make migration``.

Override / escape hatch: ``Command.autodetector`` of that command, or a
``makemigrations`` command of your own in an app listed before ``karni``
(Django's own detector: ``django.db.migrations.autodetector.MigrationAutodetector``).
"""

from __future__ import annotations

from typing import Any

from django.db import migrations, models
from django.db.migrations.autodetector import MigrationAutodetector, OperationDependency

__all__ = ["KarniAutodetector", "attached_to_field"]


def _mentions(item: Any, name: str) -> bool:
    """Whether an index or constraint refers to the field ``name``."""
    for attr in ("fields", "include"):
        if name in (getattr(item, attr, None) or ()):
            return True
    for expression in getattr(item, "expressions", None) or ():
        if hasattr(expression, "flatten") and any(
            isinstance(node, models.F) and str(node.name).split("__")[0] == name
            for node in expression.flatten()
        ):
            return True
    for attr in ("condition", "check"):
        if _q_mentions(getattr(item, attr, None), name):
            return True
    return False


def _q_mentions(node: Any, name: str) -> bool:
    if not isinstance(node, models.Q):
        return False
    for child in node.children:
        if isinstance(child, models.Q):
            if _q_mentions(child, name):
                return True
        elif isinstance(child, tuple) and str(child[0]).split("__")[0] == name:
            return True
    return False


def attached_to_field(options: dict[str, Any], name: str) -> tuple[list[Any], list[Any]]:
    """The indexes and the constraints of a model state's ``options`` that name ``name``."""
    indexes = [item for item in options.get("indexes") or [] if _mentions(item, name)]
    constraints = [item for item in options.get("constraints") or [] if _mentions(item, name)]
    return indexes, constraints


def _database_definition(autodetector: MigrationAutodetector, field: models.Field) -> Any:
    """The field's deconstruction without the attributes the database never sees."""
    _, path, args, kwargs = field.deconstruct()
    kwargs = {key: value for key, value in kwargs.items() if key not in field.non_db_attrs}
    return autodetector.deep_deconstruct((path, args, kwargs))


def _together_names(operation: migrations.AlterUniqueTogether, name: str) -> bool:
    """Whether an ``AlterUniqueTogether`` sets an entry that holds the field ``name``."""
    return any(name in entry for entry in operation.unique_together or ())


class KarniAutodetector(MigrationAutodetector):
    """Experimental. Django's detector, re-creating a generated field whose definition changed."""

    # The generated fields re-created in this run, and the unique_together each of their
    # models gets back once they are added again (set in generate_removed_altered_unique_together).
    _recreated: frozenset[tuple[str, str, str]] = frozenset()
    _together_restores: tuple[tuple[str, str, frozenset[tuple[str, ...]]], ...] = ()

    def _redefined_generated(self) -> list[tuple[str, str, str]]:
        keys = []
        for app_label, model_name, field_name in sorted(self.old_field_keys & self.new_field_keys):
            old_model = self.renamed_models.get((app_label, model_name), model_name)
            old_name = self.renamed_fields.get((app_label, model_name, field_name), field_name)
            if old_name != field_name:
                continue
            old_field = self.from_state.models[app_label, old_model].get_field(old_name)
            new_field = self.to_state.models[app_label, model_name].get_field(field_name)
            if not (old_field.generated or new_field.generated):
                continue
            if _database_definition(self, old_field) != _database_definition(self, new_field):
                keys.append((app_label, model_name, field_name))
        return keys

    def _shared_together(self, app_label: str, model_name: str) -> frozenset[tuple[str, ...]]:
        """The ``unique_together`` entries the old and the new model both have.

        It is what the model has while its generated fields are re-created: Django's own
        operations take away what the new state drops before any field is removed, and add
        what it gains after.
        """
        old_model = self.renamed_models.get((app_label, model_name), model_name)
        old_value = self.from_state.models[app_label, old_model].options.get("unique_together")
        new_value = self.to_state.models[app_label, model_name].options.get("unique_together")
        old = {
            tuple(self.renamed_fields.get((app_label, model_name, n), n) for n in entry)
            for entry in old_value or ()
        }
        return frozenset(old & {tuple(entry) for entry in new_value or ()})

    def generate_removed_altered_unique_together(self) -> None:
        """Set aside each ``unique_together`` entry that names a re-created generated field.

        The entries come back after the field is added (:meth:`generate_altered_unique_together`).
        """
        self._recreated = frozenset(self._redefined_generated())
        super().generate_removed_altered_unique_together()
        fields: dict[tuple[str, str], set[str]] = {}
        for app_label, model_name, field_name in self._recreated:
            fields.setdefault((app_label, model_name), set()).add(field_name)
        restores = []
        for (app_label, model_name), names in sorted(fields.items()):
            shared = self._shared_together(app_label, model_name)
            naming = {entry for entry in shared if names.intersection(entry)}
            if not naming:
                continue
            self.add_operation(
                app_label,
                migrations.AlterUniqueTogether(
                    name=model_name, unique_together=set(shared - naming)
                ),
            )
            restores.append((app_label, model_name, shared))
        self._together_restores = tuple(restores)

    def generate_altered_unique_together(self) -> None:
        for app_label, model_name, shared in self._together_restores:
            self.add_operation(
                app_label,
                migrations.AlterUniqueTogether(name=model_name, unique_together=set(shared)),
            )
        super().generate_altered_unique_together()

    def add_operation(
        self,
        app_label: str,
        operation: Any,
        dependencies: Any = None,
        beginning: bool = False,
    ) -> None:
        """Django's, with one rule more: a ``unique_together`` that names a re-created
        generated field is set after the field is added again."""
        if isinstance(operation, migrations.AlterUniqueTogether):
            created = [
                OperationDependency(
                    app_label, model_name, field_name, OperationDependency.Type.CREATE
                )
                for label, model_name, field_name in sorted(self._recreated)
                if label == app_label
                and model_name == operation.name_lower
                and _together_names(operation, field_name)
            ]
            if created:
                dependencies = [*(dependencies or []), *created]
        super().add_operation(app_label, operation, dependencies, beginning)

    def check_dependency(self, operation: Any, dependency: Any) -> bool:
        """Django's, except that removing a re-created generated field waits only for the
        ``unique_together`` changes that leave the field out (the others follow its re-adding)."""
        if (
            dependency.type == OperationDependency.Type.ALTER_FOO_TOGETHER
            and dependency.field_name is not None
            and isinstance(operation, migrations.AlterUniqueTogether)
            and (dependency.app_label, dependency.model_name_lower, dependency.field_name)
            in self._recreated
            and _together_names(operation, dependency.field_name)
        ):
            return False
        return bool(super().check_dependency(operation, dependency))

    def generate_altered_fields(self) -> None:
        redefined = self._redefined_generated()
        old_keys: set[tuple[str, str, str]] = self.old_field_keys  # type: ignore[has-type]
        new_keys: set[tuple[str, str, str]] = self.new_field_keys  # type: ignore[has-type]
        self.old_field_keys = old_keys - set(redefined)
        self.new_field_keys = new_keys - set(redefined)
        try:
            super().generate_altered_fields()
        finally:
            self.old_field_keys, self.new_field_keys = old_keys, new_keys
        for app_label, model_name, field_name in redefined:
            self._recreate_generated(app_label, model_name, field_name)

    def _recreate_generated(self, app_label: str, model_name: str, field_name: str) -> None:
        old_model = self.renamed_models.get((app_label, model_name), model_name)
        old_options = self.from_state.models[app_label, old_model].options
        new_options = self.to_state.models[app_label, model_name].options
        old_indexes, old_constraints = attached_to_field(old_options, field_name)
        new_indexes, new_constraints = attached_to_field(new_options, field_name)
        # An attachment that changes in the same run is already removed and added by Django.
        kept_indexes = [item for item in old_indexes if item in new_indexes]
        kept_constraints = [item for item in old_constraints if item in new_constraints]
        for index in kept_indexes:
            self.add_operation(
                app_label, migrations.RemoveIndex(model_name=model_name, name=index.name)
            )
        for constraint in kept_constraints:
            self.add_operation(
                app_label, migrations.RemoveConstraint(model_name=model_name, name=constraint.name)
            )
        self._generate_removed_field(app_label, model_name, field_name)
        self._generate_added_field(app_label, model_name, field_name)
        created = [
            OperationDependency(app_label, model_name, field_name, OperationDependency.Type.CREATE)
        ]
        for index in kept_indexes:
            self.add_operation(
                app_label,
                migrations.AddIndex(model_name=model_name, index=index),
                dependencies=created,
            )
        for constraint in kept_constraints:
            self.add_operation(
                app_label,
                migrations.AddConstraint(model_name=model_name, constraint=constraint),
                dependencies=created,
            )
