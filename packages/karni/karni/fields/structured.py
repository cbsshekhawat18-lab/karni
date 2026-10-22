"""JSON documents, indexed when the model says they are queried.

``JSONField`` is Django's (``jsonb`` on PostgreSQL). ``queried=True`` adds a
GIN index so containment and key lookups (``meta__contains={...}``,
``meta__has_key="x"``) use an index instead of reading every row. Leave it
off for a document that is only read back whole: a GIN index costs on every
write.

Override / escape hatch: ``models.JSONField`` plus a ``GinIndex`` in
``Meta.indexes`` is the plain equivalent.
"""

from __future__ import annotations

from typing import Any

from django.db import models

from karni.fields.base import KarniField
from karni.fields.indexes import GinIndex

__all__ = ["JSONField"]


class JSONField(KarniField, models.JSONField):
    """Django's JSONField; ``queried=True`` adds a GIN index on PostgreSQL."""

    plain_django = "models.JSONField"

    def __init__(self, *args: Any, queried: bool = False, **kwargs: Any) -> None:
        self.queried = queried
        super().__init__(*args, **kwargs)

    def karni_indexes(self, model: type[models.Model]) -> list[tuple[Any, str]]:
        if not self.queried:
            return []
        return [
            (
                GinIndex(fields=[self.name]),
                f"JSONField(queried=True): containment and key lookups on {self.name}",
            )
        ]

    def karni_column(self) -> str:
        return "JSONField: jsonb" + (" (queried: GIN)" if self.queried else "")

    def backend_problem(self, connection: Any) -> tuple[str, str] | None:
        if not self.queried or connection.vendor == "postgresql":
            return None
        return "warning", self.postgres_only_text()

    def postgres_only_text(self) -> str:
        return "the GIN index queried=True asks for (lookups read every row)"

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.queried:
            kwargs["queried"] = True
        return name, self._public_path(path), args, kwargs

    def karni_sample(self, ctx: Any) -> Any:
        return NotImplemented
