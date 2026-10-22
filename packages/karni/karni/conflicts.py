"""When the database refuses a write: a coded Karni error instead of a bare ``IntegrityError``.

The guarantees of :mod:`karni.lifecycle` and :mod:`karni.capacity` live in
the database (CHECK and EXCLUDE constraints, conditional updates), so the
refusal arrives as ``IntegrityError`` — correct, and useless to the person
who has to react to it. This module turns it into an error that names what
conflicted:

* :class:`KarniConflict` — the base: the write conflicts with data already
  there (a taken slot, a sold-out tier, a state changed by someone else).
  It is also an ``IntegrityError``, so existing ``except IntegrityError``
  code keeps working; the API answers **409** with :meth:`KarniConflict.payload`.
* :func:`translate` — ``IntegrityError`` → the matching Karni error, from
  the constraint the database names (PostgreSQL) or the CHECK text (SQLite).
* :func:`api_exception` — what ``BaseViewSet`` raises in place of a Karni
  error: a 400 for an illegal transition, a 409 for a conflict.

Override / escape hatch: catch :class:`KarniConflict` (or ``IntegrityError``)
yourself; override ``BaseViewSet.handle_exception`` to shape the response.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.apps import apps
from django.db import IntegrityError, models

from karni.errorcodes import KarniError

__all__ = [
    "KarniConflict",
    "Violation",
    "api_exception",
    "translate",
    "violation",
]

#: PostgreSQL's identifier limit: longer constraint names are truncated.
_PG_NAME_LENGTH = 63


class KarniConflict(KarniError, IntegrityError):
    """The write conflicts with data that is already there (HTTP 409).

    ``field`` is the field the conflict is about (or ``None``); ``details``
    is the machine-readable part (ids, ranges, counts) the API returns as
    ``conflict``.
    """

    status = 409

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        KarniError.__init__(self, message, code=code)
        self.field = field
        self.details: dict[str, Any] = details or {}

    def payload(self) -> dict[str, Any]:
        """The 409 body: ``detail`` (the message), ``code``, ``field`` and ``conflict``."""
        return {
            "detail": str(self),
            "code": self.code,
            "field": self.field,
            "conflict": self.details,
        }


@dataclass(frozen=True)
class Violation:
    """What the database said: the kind of constraint, its name, the table, the message."""

    kind: str
    constraint: str | None
    table: str | None
    message: str


_SQLSTATES = {"23P01": "exclusion", "23514": "check", "23505": "unique", "23502": "not_null"}


def violation(exc: BaseException) -> Violation:
    """Read the constraint behind an ``IntegrityError`` (psycopg's diagnostics, SQLite's text)."""
    cause = exc.__cause__ or exc
    diag = getattr(cause, "diag", None)
    sqlstate = getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)
    message = str(cause)
    kind = _SQLSTATES.get(str(sqlstate), "")
    if not kind:
        lowered = message.lower()
        if "check constraint failed" in lowered:
            kind = "check"
        elif "unique constraint failed" in lowered:
            kind = "unique"
        else:
            kind = "other"
    return Violation(
        kind=kind,
        constraint=getattr(diag, "constraint_name", None),
        table=getattr(diag, "table_name", None),
        message=message,
    )


def same_constraint(declared: str, reported: str | None) -> bool:
    """Whether ``reported`` (as PostgreSQL names it) is the constraint ``declared``."""
    return reported is not None and declared[:_PG_NAME_LENGTH] == reported


def column_check(found: Violation, model: type[models.Model], column: str) -> bool:
    """Whether a CHECK violation is the column-level CHECK of ``column`` on ``model``.

    PostgreSQL names a column CHECK ``<table>_<column>_check`` (or with a
    hash before ``_check`` when a migration re-adds it); SQLite reports
    ``CHECK constraint failed: <column>`` (older versions: the expression,
    which quotes the column).
    """
    if found.kind != "check":
        return False
    if found.constraint is not None:
        prefix = f"{model._meta.db_table}_{column}"[:_PG_NAME_LENGTH]
        return found.constraint.startswith(prefix) and found.constraint.endswith("_check")
    reported = found.message.split("failed:", 1)[-1].strip()
    return reported == column or f'"{column}"' in reported


def _model_for_table(table: str | None) -> type[models.Model] | None:
    if table is None:
        return None
    for model in apps.get_models():
        if model._meta.db_table == table:
            return model
    return None


def translate(
    exc: BaseException,
    *,
    model: type[models.Model] | None = None,
    instance: models.Model | None = None,
    using: str | None = None,
) -> KarniError | None:
    """The Karni error for ``exc``, or ``None`` when no Karni constraint was violated.

    With ``instance`` (the row being saved) the error names the existing row
    it conflicts with; this runs a query, so call it after the failed
    statement's savepoint has been rolled back.
    """
    if isinstance(exc, KarniError):
        return exc
    if not isinstance(exc, IntegrityError):
        return None
    found = violation(exc)
    model = model or (type(instance) if instance is not None else None)
    model = model or _model_for_table(found.table)
    if model is None:
        return None
    from karni.capacity import capacity_conflict
    from karni.constraints import overlap_conflict
    from karni.lifecycle import undeclared_state

    for translator in (overlap_conflict, capacity_conflict, undeclared_state):
        error = translator(found, model, instance, using)
        if error is not None:
            return error
    return None


def api_exception(exc: BaseException) -> Exception | None:
    """The DRF exception for a Karni lifecycle/capacity error, or ``None`` to leave ``exc`` alone.

    An illegal transition is a 400 naming the field; a conflict (taken slot,
    sold out, changed concurrently) is a 409 with :meth:`KarniConflict.payload`;
    an ``IntegrityError`` from a Karni constraint is translated first.
    """
    from rest_framework.exceptions import APIException

    from karni.exceptions import api_error
    from karni.lifecycle import IllegalTransition

    error = translate(exc) if isinstance(exc, IntegrityError) else exc
    if isinstance(error, IllegalTransition):
        return api_error(error.code, error.message, field=error.field)
    if isinstance(error, KarniConflict):
        response = APIException(error.message, code=error.code)
        response.status_code = error.status
        response.detail = error.payload()
        return response
    return None
