"""Text fields whose OpenAPI property names a format a client renders them by.

A model field with an ``openapi_format`` attribute (``MarkdownField`` has
``"markdown"``) becomes a :class:`FormattedCharField` in the generated
serializer: the same ``CharField`` DRF builds for a ``TextField``, plus that
``format`` on its property in the schema
(``{"type": "string", "format": "markdown"}``). ``@karni/ui`` reads it:
ResourceForm edits a markdown field with Write and Preview tabs and
ResourceDetail shows it formatted and sanitized.

A :class:`~karni.fields.MoneyField` becomes a :class:`MoneyDecimalField`: the
same ``DecimalField``, plus ``x-karni-money`` on its property, the currency it
is in: ``{"currency": "EUR"}`` for a fixed one, ``{"currency_field":
"price_currency"}`` for a currency per row. ``@karni/ui``
reads it: tables and details show the amount in its currency (``$60.00``).

Override / escape hatch: give your own ``TextField`` subclass an
``openapi_format`` to publish another format, or declare the field on a
hand-written serializer to publish none.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.openapi import AutoSchema
from rest_framework import serializers

__all__ = ["FormattedCharField", "MoneyDecimalField", "format_of", "money_of"]


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


class MoneyDecimalField(serializers.DecimalField):
    """A ``DecimalField`` whose schema property carries ``x-karni-money``."""

    def __init__(self, *args: Any, money: dict[str, str] | None = None, **kwargs: Any) -> None:
        self.money = dict(money or {})
        super().__init__(*args, **kwargs)


class MoneyDecimalFieldExtension(OpenApiSerializerFieldExtension):
    """The stock decimal schema plus ``x-karni-money``."""

    target_class = "karni.api.formats.MoneyDecimalField"
    match_subclasses = True

    def map_serializer_field(self, auto_schema: AutoSchema, direction: Any) -> Any:
        schema = auto_schema._map_serializer_field(self.target, direction, bypass_extensions=True)
        money = getattr(self.target, "money", None)
        if isinstance(schema, dict) and money:
            schema["x-karni-money"] = dict(money)
        return schema


def money_of(model_field: Any) -> dict[str, str] | None:
    """A MoneyField's currency, as ``x-karni-money`` gives it, else ``None``."""
    from karni.fields.money import MoneyField

    if not isinstance(model_field, MoneyField):
        return None
    if model_field.currency:
        return {"currency": str(model_field.currency)}
    if model_field.currency_field:
        return {"currency_field": str(model_field.currency_field)}
    return None
