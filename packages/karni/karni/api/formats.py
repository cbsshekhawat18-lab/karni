"""Text fields whose OpenAPI property names a format a client renders them by.

A model field with an ``openapi_format`` attribute (``MarkdownField`` has
``"markdown"``) becomes a :class:`FormattedCharField` in the generated
serializer: the same ``CharField`` DRF builds for a ``TextField``, plus that
``format`` on its property in the schema
(``{"type": "string", "format": "markdown"}``). ``@karni/ui`` reads it:
ResourceForm edits a markdown field with Write and Preview tabs and
ResourceDetail shows it formatted and sanitized.

Override / escape hatch: give your own ``TextField`` subclass an
``openapi_format`` to publish another format, or declare the field on a
hand-written serializer to publish none.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.openapi import AutoSchema
from rest_framework import serializers

__all__ = ["FormattedCharField", "format_of"]


class FormattedCharField(serializers.CharField):
    """A ``CharField`` whose schema property carries ``openapi_format``."""

    def __init__(self, *args: Any, openapi_format: str = "", **kwargs: Any) -> None:
        self.openapi_format = openapi_format
        super().__init__(*args, **kwargs)


class FormattedCharFieldExtension(OpenApiSerializerFieldExtension):
    """The stock string schema plus ``format``."""

    target_class = "karni.api.formats.FormattedCharField"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: AutoSchema, direction: Any) -> Any:
        schema = auto_schema._map_serializer_field(self.target, direction, bypass_extensions=True)
        found = getattr(self.target, "openapi_format", "")
        if isinstance(schema, dict) and found:
            schema["format"] = found
        return schema


def format_of(model_field: Any) -> str | None:
    """The ``openapi_format`` a model field declares (a non-empty string), else ``None``."""
    found = getattr(model_field, "openapi_format", None)
    return found if isinstance(found, str) and found else None
