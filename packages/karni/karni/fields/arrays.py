"""PostgreSQL arrays with a GIN index: ``ArrayField(models.CharField(max_length=40))``.

Django's ``ArrayField`` plus a GIN index (``indexed=True`` by default) that
serves ``tags__contains=[...]``, ``tags__overlap=[...]`` and
``tags__contained_by=[...]``. Arrays exist only on PostgreSQL: on any other
database a model with an ``ArrayField`` cannot be migrated, and system check
``karni.E964`` says so at boot instead of letting ``migrate`` fail with a
syntax error. Use a ``JSONField`` holding a list where the project must also
run elsewhere.

This module imports ``django.contrib.postgres.fields``, which needs a
PostgreSQL driver (``psycopg``); ``karni.fields.ArrayField`` imports it on
first use.

Override / escape hatch: ``django.contrib.postgres.fields.ArrayField`` with
``indexed=False`` semantics is the plain replacement.
"""

from __future__ import annotations

from typing import Any

from django.contrib.postgres.fields import ArrayField as DjangoArrayField
from django.db import models

from karni.fields.base import KarniField
from karni.fields.indexes import GinIndex

__all__ = ["ArrayField"]


class ArrayField(KarniField, DjangoArrayField):
    """A PostgreSQL array; GIN-indexed unless ``indexed=False``."""

    backend_support = "postgres"
    plain_django = "django.contrib.postgres.fields.ArrayField"

    def __init__(self, base_field: Any, *args: Any, indexed: bool = True, **kwargs: Any) -> None:
        self.indexed = indexed
        super().__init__(base_field, *args, **kwargs)

    def karni_indexes(self, model: type[models.Model]) -> list[tuple[Any, str]]:
        if not self.indexed:
            return []
        return [
            (
                GinIndex(fields=[self.name]),
                f"ArrayField: contains/overlap lookups on {self.name}",
            )
        ]

    def karni_column(self) -> str:
        return "ArrayField: array" + (" (GIN)" if self.indexed else "")

    def postgres_only_text(self) -> str:
        return (
            "array columns exist only on PostgreSQL, so the table cannot be created here. Use "
            "karni.fields.JSONField (a list) for a portable model"
        )

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if not self.indexed:
            kwargs["indexed"] = False
        return name, self._public_path(path), args, kwargs

    def karni_sample(self, ctx: Any) -> Any:
        return []
