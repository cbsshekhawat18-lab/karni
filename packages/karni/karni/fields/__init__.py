"""Karni's typed model fields: the column says what it holds, the database enforces it.

Lifecycle and limited resources (see ``docs/lifecycle-and-capacity.md``):

* :class:`StateField` — declared states and legal transitions, a CHECK on
  the column, conditional updates (:mod:`karni.fields.state`).
* :class:`CapacityField` — a remaining count the database keeps at or above
  zero, consumed with :func:`karni.capacity.reserve`
  (:mod:`karni.fields.capacity`).
* :class:`DateRangeField` / :class:`DateTimeRangeField` — PostgreSQL range
  columns (:mod:`karni.fields.ranges`, imported on first use: they need
  psycopg).

Override / escape hatch: each field is a plain Django field subclass; import
Django's own field instead to opt out of what Karni adds.
"""

from __future__ import annotations

from typing import Any

# lifecycle and limited resources
from karni.fields.capacity import CapacityField
from karni.fields.state import StateField

__all__ = ["CapacityField", "DateRangeField", "DateTimeRangeField", "StateField"]

#: Names served lazily: the range fields import psycopg.
_LAZY = {"DateRangeField": "karni.fields.ranges", "DateTimeRangeField": "karni.fields.ranges"}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        from importlib import import_module

        return getattr(import_module(_LAZY[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
