"""The two halves of the cache key: the template version and the data version.

* :func:`template_version` hashes the template's source, the source of every
  template it extends or includes by a constant name, and the render options
  (page size, renderer). Editing the template, or the base template a project
  overrides, gives a new version.
* :func:`data_version` hashes the context a report's ``get_context`` returns,
  as canonical JSON: a model instance counts with every concrete field
  (``updated_at`` included, so any saved change of the row counts), a
  queryset with its rows (evaluated once: the template reuses its cache).

Override / escape hatch: ``Report.get_template_version`` and
``Report.get_data_version`` replace either one per report.
"""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from django.db import models
from django.db.models.fields.files import FieldFile
from karni.exceptions import KarniTypeError

__all__ = ["data_version", "encode", "template_sources", "template_version"]

#: The text ``object.__repr__`` gives: it changes every run, so it is not data.
_ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+>")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def template_sources(name: str) -> list[tuple[str, str]]:
    """``(name, source)`` of the template and of each one it extends or includes, in order."""
    from django.template import loader

    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def walk(current: str) -> None:
        if current in seen:
            return
        seen.add(current)
        template: Any = loader.get_template(current)
        inner = getattr(template, "template", template)
        found.append((current, str(getattr(inner, "source", "") or "")))
        for child in _referenced(inner):
            walk(child)

    walk(name)
    return found


def _referenced(template: Any) -> list[str]:
    """The constant names ``{% extends %}`` and ``{% include %}`` use in a Django template."""
    from django.template.loader_tags import ExtendsNode, IncludeNode

    nodelist = getattr(template, "nodelist", None)
    if nodelist is None:
        return []
    names: list[str] = []
    for node in nodelist.get_nodes_by_type(ExtendsNode):
        names += _constant(node.parent_name)
    for node in nodelist.get_nodes_by_type(IncludeNode):
        names += _constant(node.template)
    return names


def _constant(expression: Any) -> list[str]:
    value = getattr(expression, "var", None)
    return [value] if isinstance(value, str) else []


def template_version(name: str, options: Mapping[str, Any] | None = None) -> str:
    """The template's version: a hash of its sources and of ``options``."""
    parts = [f"{source_name}\0{source}" for source_name, source in template_sources(name)]
    parts.append(json.dumps(dict(options or {}), sort_keys=True, default=str))
    return _digest("\0\0".join(parts))


def encode(value: Any) -> Any:
    """``value`` as plain JSON data, the same on every run (what :func:`data_version` hashes).

    :raises KarniTypeError: (``REPORT011``) for a value that has no stable
        text, such as an object without ``__str__``.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, models.Model):
        fields = {
            field.attname: encode(getattr(value, field.attname))
            for field in value._meta.concrete_fields
        }
        return {"$model": value._meta.label, "$pk": str(value.pk), **fields}
    if isinstance(value, FieldFile):
        return value.name or ""
    if isinstance(value, decimal.Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return value.total_seconds()
    if isinstance(value, bytes):
        return _digest(value.hex())
    if isinstance(value, Mapping):
        return {str(key): encode(item) for key, item in value.items()}
    if isinstance(value, set | frozenset):
        return sorted((encode(item) for item in value), key=_sort_key)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return encode(dataclasses.asdict(value))
    if isinstance(value, models.QuerySet | models.Manager | Iterable):
        # list() fills a queryset's result cache, so the template reads the same rows.
        return [encode(item) for item in _rows(value)]
    text = str(value)
    if _ADDRESS.search(text):
        raise KarniTypeError(
            f"The report's context holds {type(value).__name__} {text}, which has no stable "
            "text, so the data version would differ on every request. Put plain data in the "
            "context (a dict, a model instance, a list), give the class a __str__, or override "
            "Report.get_data_version.",
            code="REPORT011",
        )
    return text


def _rows(value: Any) -> Iterable[Any]:
    if isinstance(value, models.QuerySet):
        value._fetch_all()
        return value._result_cache or []
    if isinstance(value, models.Manager):
        return list(value.all())
    return value


def _sort_key(item: Any) -> str:
    return json.dumps(item, sort_keys=True)


def data_version(context: Mapping[str, Any]) -> str:
    """The context's version: a hash of :func:`encode`'s canonical JSON."""
    return _digest(json.dumps(encode(context), sort_keys=True, separators=(",", ":")))
