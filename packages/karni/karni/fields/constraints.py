"""Uniqueness that respects soft delete: :class:`LiveUniqueConstraint`.

A soft-deleted row stays in its table, so a plain unique index keeps its
values reserved forever: a deleted user's email can never register again, a
deleted event's slug can never be reused. ``LiveUniqueConstraint`` is a
``UniqueConstraint`` limited to live rows (``WHERE deleted_at IS NULL``), a
partial unique index that PostgreSQL and SQLite both enforce, also against
raw SQL::

    from karni.fields import LiveUniqueConstraint

    class Seat(BaseModel):
        venue = models.ForeignKey(Venue, on_delete=models.PROTECT)
        label = models.CharField(max_length=10)

        class Meta(BaseModel.Meta):
            constraints = [LiveUniqueConstraint(fields=["venue", "label"])]

``name`` is optional (a deterministic name is derived from the table and
fields); ``condition=`` narrows it further and is combined with the live-row
condition. Karni fields declared ``unique=True`` on a soft-deletable model
use it automatically.

Override / escape hatch: pass ``name=`` to pick the name; use a plain
``models.UniqueConstraint`` when deleted rows must keep their values
reserved (that is Django's default behaviour).
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.db.models import Q

from karni.fields.base import PUBLIC_PATH, SOFT_DELETE_FIELD, object_name

__all__ = ["LiveUniqueConstraint", "live_condition", "name_pending_constraints"]

#: Placeholder until the model is known (replaced in ``class_prepared``).
_PENDING = "karni_pending_live_uniq__"


def live_condition() -> Q:
    """``deleted_at IS NULL``: the rows a soft-delete model treats as existing."""
    return Q(**{f"{SOFT_DELETE_FIELD}__isnull": True})


class LiveUniqueConstraint(models.UniqueConstraint):
    """A ``UniqueConstraint`` over live rows only (see the module docstring)."""

    def __init__(
        self,
        *expressions: Any,
        fields: Any = (),
        name: str | None = None,
        condition: Q | None = None,
        **kwargs: Any,
    ) -> None:
        #: The caller's own condition, without the live-row part (what deconstruct emits).
        self.extra_condition = condition
        combined = live_condition() if condition is None else live_condition() & condition
        if not name:
            parts = list(fields) or ["expr"]
            name = _PENDING + "_".join(str(part) for part in parts)
        super().__init__(*expressions, fields=fields, name=name, condition=combined, **kwargs)

    @property
    def pending_name(self) -> bool:
        """True until the model this constraint belongs to has named it."""
        return self.name.startswith(_PENDING)

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        path, args, kwargs = super().deconstruct()
        if self.extra_condition is None:
            kwargs.pop("condition", None)
        else:
            kwargs["condition"] = self.extra_condition
        return f"{PUBLIC_PATH}.LiveUniqueConstraint", args, kwargs


def name_pending_constraints(model: type[models.Model]) -> None:
    """Give each unnamed ``LiveUniqueConstraint`` of ``model`` its deterministic name."""
    for constraint in model._meta.constraints:
        if isinstance(constraint, LiveUniqueConstraint) and constraint.pending_name:
            columns = [
                model._meta.get_field(name).column if _is_field(model, name) else str(name)
                for name in constraint.fields
            ] or ["expr", str(len(constraint.expressions))]
            constraint.name = object_name(model, columns, "live_uniq")


def _is_field(model: type[models.Model], name: str) -> bool:
    try:
        model._meta.get_field(name)
    except Exception:  # noqa: BLE001 - Django's own check reports an unknown field
        return False
    return True
