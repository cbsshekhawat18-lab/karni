"""What every Karni field shares: schema notes, contributed objects, uniqueness, naming.

A Karni field is a plain Django field (``MoneyField`` *is* a ``DecimalField``)
plus :class:`KarniField`, a mixin that declares what the field needs from the
database beyond its column:

* :meth:`KarniField.karni_constraints` / :meth:`KarniField.karni_indexes` —
  named constraints and indexes the field adds to its model's ``Meta`` when
  the model class is prepared (so ``makemigrations`` writes them, and they
  show in ``karni schema`` with the reason);
* :attr:`KarniField.backend_support` — ``portable`` (works the same on every
  database Karni supports), ``degrades`` (a PostgreSQL extra is skipped
  elsewhere, system check ``karni.W964``) or ``postgres`` (cannot work
  elsewhere, ``karni.E964``), with :meth:`KarniField.backend_problem` naming
  what is lost;
* :meth:`KarniField.karni_sample` — a valid value for test factories and
  ``karni seed`` (a country field gets a real ISO code, not a country name).

Uniqueness on soft-deletable models: a Karni field declared ``unique=True``
never carries a column-level ``UNIQUE``. It contributes a named unique
constraint instead — :class:`~karni.fields.constraints.LiveUniqueConstraint`
(``WHERE deleted_at IS NULL``) on a :class:`~karni.models.SoftDeleteModel`,
so a deleted row does not block reusing its value, and a plain
``UniqueConstraint`` elsewhere. ``field.unique`` is therefore ``False``;
:func:`is_unique` answers the question for any field.

Override / escape hatch: every Karni field takes all of its Django base
field's arguments and can be swapped for that plain Django field (the
``plain_django`` attribute names it); subclass a field and override
``karni_constraints``/``karni_indexes`` to change what it contributes.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from django.db import models
from django.db.backends.utils import names_digest
from django.db.migrations.state import StateApps
from django.db.models.signals import class_prepared

__all__ = [
    "SOFT_DELETE_FIELD",
    "KarniField",
    "SchemaNote",
    "Support",
    "contribute_constraint",
    "contribute_index",
    "is_soft_deletable",
    "is_unique",
    "object_name",
    "schema_notes",
]

Support = Literal["portable", "degrades", "postgres"]

#: The column a soft-deletable model marks deleted rows with (``SoftDeleteModel``).
SOFT_DELETE_FIELD = "deleted_at"

#: Python path prefix Karni fields, indexes and constraints deconstruct to in
#: migrations, so a module move inside ``karni.fields`` never breaks them.
PUBLIC_PATH = "karni.fields"


@dataclass(frozen=True)
class SchemaNote:
    """A database object a Karni declaration caused, and the declaration that caused it."""

    #: ``constraint`` or ``index``.
    kind: str
    #: The object's name in the database.
    name: str
    #: Which declaration caused it, in words (``"SlugField(unique=True) on a soft-deletable
    #: model: a deleted row's slug can be reused"``).
    why: str


_NOTES: weakref.WeakKeyDictionary[type[models.Model], dict[str, SchemaNote]] = (
    weakref.WeakKeyDictionary()
)


def schema_notes(model: type[models.Model]) -> dict[str, SchemaNote]:
    """Every constraint/index Karni added to ``model``, by name, with the reason."""
    return dict(_NOTES.get(model, {}))


def _note(model: type[models.Model], kind: str, name: str, why: str) -> None:
    _NOTES.setdefault(model, {})[name] = SchemaNote(kind, name, why)


def object_name(
    model: type[models.Model], columns: list[str], suffix: str, *, limit: int = 63
) -> str:
    """A deterministic constraint/index name of at most ``limit`` characters.

    ``<table>_<columns>`` truncated, then a hash of the full table, columns and
    suffix (so two names never collide), then the suffix: the scheme Django
    uses for its own index names. 63 is PostgreSQL's identifier limit; pass
    ``limit=30`` for an ``Index`` (Django's check ``models.E034``).
    """
    table = model._meta.db_table
    digest = names_digest(table, *columns, suffix, length=8)
    head = "_".join([table, *columns])
    room = limit - len(digest) - len(suffix) - 2
    name = f"{head[:room].rstrip('_')}_{digest}_{suffix}"
    return name if name[0].isalpha() else f"k{name[1:]}"


def is_soft_deletable(model: type[models.Model]) -> bool:
    """True for a :class:`~karni.models.SoftDeleteModel` (rows carry ``deleted_at``)."""
    from karni.models import SoftDeleteModel

    return isinstance(model, type) and issubclass(model, SoftDeleteModel)


def is_unique(field: Any) -> bool:
    """Whether ``field``'s values must differ per (live) row: ``unique=True`` on any field.

    Karni fields keep their uniqueness in a named constraint, so their
    ``field.unique`` is ``False``; this reads both.
    """
    return bool(getattr(field, "unique", False) or getattr(field, "karni_unique", False))


class KarniField:
    """Mixin for every Karni field (see the module docstring).

    Subclasses set the class attributes and override the hooks; the mixin
    goes first in the bases (``class MoneyField(KarniField, DecimalField)``).
    """

    #: ``portable`` · ``degrades`` (PostgreSQL extras skipped elsewhere) ·
    #: ``postgres`` (cannot work on another database).
    backend_support: ClassVar[Support] = "portable"
    #: The plain Django field this one can be replaced with.
    plain_django: ClassVar[str] = ""
    #: True when uniqueness compares values case-insensitively (``Lower()``).
    case_insensitive_unique: ClassVar[bool] = False

    #: Set from ``unique=True`` (see the module docstring); never a column UNIQUE.
    karni_unique: bool = False

    # -- what the field contributes -------------------------------------

    def karni_constraints(self, model: type[models.Model]) -> list[tuple[Any, str]]:
        """``(constraint, why)`` pairs added to ``model``'s ``Meta.constraints``.

        The unique constraint (``unique=True``) and the CHECK built from
        :meth:`check_condition`. Both are named ``Meta`` constraints rather than
        column-level SQL: Django re-creates a column CHECK only for its own
        field types when a column is altered, so a constraint is the only form
        that reaches an existing column, and it shows in the migration.
        """
        found = [self._unique_constraint(model)] if self.karni_unique else []
        condition = self.check_condition()
        if condition is not None:
            field: Any = self
            constraint = models.CheckConstraint(
                condition=condition, name=object_name(model, [field.column], "check")
            )
            found.append((constraint, self.karni_column()))
        return found

    def check_condition(self) -> Any:
        """The condition every row must meet (a database CHECK), or ``None``."""
        return None

    def karni_indexes(self, model: type[models.Model]) -> list[tuple[Any, str]]:
        """``(index, why)`` pairs added to ``model``'s ``Meta.indexes``."""
        return []

    def karni_column(self) -> str:
        """Why the column has its type and column-level CHECK (for ``karni schema``)."""
        return type(self).__name__

    def backend_problem(self, connection: Any) -> tuple[str, str] | None:
        """``("warning" | "error", what is lost)`` on ``connection``'s database, else ``None``."""
        if self.backend_support == "portable" or connection.vendor == "postgresql":
            return None
        level = "error" if self.backend_support == "postgres" else "warning"
        return level, self.postgres_only_text()

    def postgres_only_text(self) -> str:
        """What this field loses (or why it cannot work) off PostgreSQL."""
        return "PostgreSQL-only behaviour"

    def karni_sample(self, ctx: Any) -> Any:
        """A valid value for factories and seeds; ``NotImplemented`` lets inference decide."""
        return NotImplemented

    # -- uniqueness ------------------------------------------------------

    def _pop_unique(self, kwargs: dict[str, Any], default: bool = False) -> None:
        """Move ``unique`` out of the Django kwargs into :attr:`karni_unique`."""
        self.karni_unique = bool(kwargs.pop("unique", default))

    def _unique_constraint(self, model: type[models.Model]) -> tuple[Any, str]:
        from django.db.models.functions import Lower

        from karni.fields.constraints import LiveUniqueConstraint

        field: Any = self
        soft = is_soft_deletable(model)
        name = object_name(model, [field.column], "uniq")
        kind = type(self).__name__
        message = None
        if self.case_insensitive_unique:
            message = (
                f"A {model._meta.verbose_name} with this {field.verbose_name} already exists "
                "(compared case-insensitively)."
            )
        args: tuple[Any, ...] = (Lower(field.name),) if self.case_insensitive_unique else ()
        kwargs: dict[str, Any] = {"name": name}
        if not args:
            kwargs["fields"] = [field.name]
        if message:
            kwargs["violation_error_message"] = message
        constraint = (
            LiveUniqueConstraint(*args, **kwargs)
            if soft
            else models.UniqueConstraint(*args, **kwargs)
        )
        how = "lower-cased, " if self.case_insensitive_unique else ""
        scope = (
            "among live rows (WHERE deleted_at IS NULL): a soft-deleted row's value can be reused"
            if soft
            else "across every row"
        )
        return constraint, f"{kind}(unique=True): unique, {how}{scope}"

    def _unique_deconstruct(self, kwargs: dict[str, Any], default: bool = False) -> None:
        if self.karni_unique != default:
            kwargs["unique"] = self.karni_unique
        else:
            kwargs.pop("unique", None)

    def _public_path(self, path: str) -> str:
        return f"{PUBLIC_PATH}.{type(self).__name__}" if path.startswith("karni.") else path


# -- contributed objects -------------------------------------------------------


def contribute_constraint(model: type[models.Model], constraint: Any, why: str) -> None:
    """Add ``constraint`` to ``model``'s ``Meta.constraints`` (once) and record why.

    For field and range authors: call it from a ``class_prepared`` receiver
    or return the pair from :meth:`KarniField.karni_constraints`. Skipped for
    the historical models migrations build: their constraints come from the
    migration files.
    """
    meta = model._meta
    if isinstance(meta.apps, StateApps):
        return
    if all(existing.name != constraint.name for existing in meta.constraints):
        meta.constraints = [*meta.constraints, constraint]
        meta.original_attrs["constraints"] = meta.constraints
        meta.__dict__.pop("total_unique_constraints", None)
    _note(model, "constraint", constraint.name, why)


def contribute_index(model: type[models.Model], index: Any, why: str) -> None:
    """Add ``index`` to ``model``'s ``Meta.indexes`` (once) and record why.

    The hook range fields (GiST) and other field types use: an unnamed index
    is named the way Django names ``Meta.indexes`` entries.
    """
    meta = model._meta
    if isinstance(meta.apps, StateApps):
        return
    if not index.name:
        index.set_name_with_model(model)
    if all(existing.name != index.name for existing in meta.indexes):
        meta.indexes = [*meta.indexes, index]
        meta.original_attrs["indexes"] = meta.indexes
    _note(model, "index", index.name, why)


def _prepare(sender: type[models.Model], **kwargs: Any) -> None:
    """``class_prepared``: add what Karni fields and ``class Karni`` options contribute."""
    meta = sender._meta
    if meta.abstract or meta.proxy or isinstance(meta.apps, StateApps):
        return
    from karni.fields.constraints import name_pending_constraints
    from karni.fields.indexes import append_only_indexes

    name_pending_constraints(sender)
    for model_field in meta.local_fields:
        if not isinstance(model_field, KarniField):
            continue
        for constraint, why in model_field.karni_constraints(sender):
            contribute_constraint(sender, constraint, why)
        for index, why in model_field.karni_indexes(sender):
            contribute_index(sender, index, why)
    append_only_indexes(sender)


class_prepared.connect(_prepare, dispatch_uid="karni.fields.prepare")
