"""What a model's columns are, for the user asking — the one description both directions use.

A :class:`ColumnSpec` per serializer field: its kind, whether this user may
read or write it (``Karni.field_roles``, ``APIMeta``), the choices of a
choice field, the target and lookup field of a relation (how a file names a
related row), and an example value for the template. Export writes the
readable specs; import accepts the writable ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from rest_framework import serializers
from rest_framework.relations import ManyRelatedField, RelatedField

from karni.meta import import_options, natural_key

__all__ = ["ColumnSpec", "column_specs", "exportable", "importable"]

#: Kinds of columns a file can carry; ``file`` and ``other`` export but never import.
KINDS = (
    "text",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "choice",
    "relation",
    "relations",
    "json",
    "file",
    "other",
)


@dataclass(frozen=True)
class ColumnSpec:
    """One column: a serializer field as the file sees it."""

    name: str
    label: str
    kind: str
    required: bool
    readable: bool
    writable: bool
    choices: tuple[tuple[str, str], ...] = ()
    target: str | None = None
    lookup: str | None = None
    help: str = ""
    key: bool = False

    @property
    def example(self) -> Any:
        """One plausible value for the template's example row."""
        if self.kind == "choice" and self.choices:
            return self.choices[0][0]
        if self.kind == "relation":
            return f"<{self.lookup or 'id'} of a {self.target or 'row'}>"
        if self.kind == "relations":
            return f"<{self.lookup or 'id'}|<{self.lookup or 'id'}>"
        return {
            "text": self.label,
            "integer": 1,
            "decimal": "9.99",
            "boolean": "true",
            "date": "2026-01-31",
            "datetime": "2026-01-31T09:00:00Z",
            "json": "{}",
            "file": "",
            "other": "",
        }.get(self.kind, "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
            "readable": self.readable,
            "writable": self.writable,
            "choices": [{"value": value, "label": label} for value, label in self.choices],
            "target": self.target,
            "lookup": self.lookup,
            "help": self.help,
            "key": self.key,
        }


def _kind(field: serializers.Field) -> str:
    if isinstance(field, ManyRelatedField | serializers.ListSerializer):
        return "relations"
    if isinstance(field, RelatedField | serializers.BaseSerializer):
        return "relation"
    if isinstance(field, serializers.MultipleChoiceField):
        return "other"
    if isinstance(field, serializers.ChoiceField):
        return "choice"
    if isinstance(field, serializers.BooleanField):
        return "boolean"
    if isinstance(field, serializers.IntegerField):
        return "integer"
    if isinstance(field, serializers.DecimalField | serializers.FloatField):
        return "decimal"
    if isinstance(field, serializers.DateTimeField):
        return "datetime"
    if isinstance(field, serializers.DateField):
        return "date"
    if isinstance(field, serializers.FileField):
        return "file"
    if isinstance(field, serializers.JSONField | serializers.DictField | serializers.ListField):
        return "json"
    if isinstance(field, serializers.CharField | serializers.UUIDField):
        return "text"
    return "other"


def _target(
    model: type[models.Model], name: str, field: serializers.Field
) -> type[models.Model] | None:
    """The model a relation field points at (a read-only field carries no queryset)."""
    child = getattr(field, "child_relation", None) or field
    queryset = getattr(child, "queryset", None)
    if queryset is not None:
        model_class: type[models.Model] = queryset.model
        return model_class
    meta = getattr(child, "Meta", None)
    declared = getattr(meta, "model", None)
    if declared is not None:
        return declared  # type: ignore[no-any-return]
    try:
        model_field = model._meta.get_field(getattr(field, "source", None) or name)
    except FieldDoesNotExist:
        return None
    return getattr(model_field, "related_model", None)


def column_specs(
    model: type[models.Model], serializer: serializers.BaseSerializer[Any]
) -> list[ColumnSpec]:
    """The columns of ``model`` as ``serializer`` (built for the user) exposes them."""
    options = import_options(model)
    key_names = {model._meta.pk.name, options.key} - {None}
    specs: list[ColumnSpec] = []
    for name, field in serializer.fields.items():
        kind = _kind(field)
        target = _target(model, name, field) if kind in ("relation", "relations") else None
        choices: tuple[tuple[str, str], ...] = ()
        if kind == "choice":
            choices = tuple(
                (str(value), str(label)) for value, label in getattr(field, "choices", {}).items()
            )
        lookup = None
        if target is not None:
            lookup = options.lookups.get(name) or natural_key(target)
        writable = not field.read_only and kind not in ("file", "other")
        specs.append(
            ColumnSpec(
                name=name,
                label=str(getattr(field, "label", None) or name.replace("_", " ")),
                kind=kind,
                required=bool(field.required and not field.read_only),
                readable=not field.write_only,
                writable=writable,
                choices=choices,
                target=target._meta.label_lower if target is not None else None,
                lookup=lookup,
                help=str(getattr(field, "help_text", "") or ""),
                key=name in key_names,
            )
        )
    return specs


def exportable(specs: list[ColumnSpec]) -> list[ColumnSpec]:
    """The columns an export writes: everything the user may read."""
    return [spec for spec in specs if spec.readable]


def importable(specs: list[ColumnSpec]) -> list[ColumnSpec]:
    """The columns an import accepts: what the user may write, plus the key that matches rows."""
    return [spec for spec in specs if spec.writable or spec.key]
