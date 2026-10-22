"""Export a queryset as CSV or XLSX — what the user may see, written so it imports back.

Rows are whatever queryset the caller already scoped (a viewset's filtered,
read-scoped queryset; an admin changelist selection); columns are the
serializer's readable fields for this user (``Karni.field_roles`` applied by
the serializer itself). Relations are written as the target's
``Karni.natural_key`` when it has one, else the primary key; to-many
relations join their values with ``|``. A related row the user may not read
(:mod:`karni.api.related`: the target's API read scope, or the scope the
serializer context names, such as the admin's) is never named by its natural
key: a to-one keeps its primary key, as the API shows it, and a to-many
leaves it out. CSV streams; XLSX is built in memory (``KARNI_EXPORT_MAX_ROWS``
caps both).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from django.conf import settings
from django.db.models import Model, QuerySet
from django.http import HttpResponse, StreamingHttpResponse
from rest_framework import serializers
from rest_framework.renderers import BaseRenderer

from karni.exceptions import KarniValueError
from karni.transfer.fields import ColumnSpec, column_specs, exportable
from karni.transfer.formats import CONTENT_TYPES, csv_lines, detect_format, xlsx_bytes

__all__ = ["CSVRenderer", "XLSXRenderer", "export_response", "export_rows", "max_export_rows"]

CHUNK = 500


class _FileRenderer(BaseRenderer):
    """Lets ``?format=csv|xlsx`` pick the file through DRF's own negotiation.

    The file itself is a plain ``HttpResponse`` that never reaches a renderer;
    only an error body does, and that is rendered as JSON.
    """

    media_type = "application/json"
    charset = "utf-8"

    def render(
        self, data: Any, accepted_media_type: Any = None, renderer_context: Any = None
    ) -> bytes:
        import json

        return json.dumps(data, default=str).encode("utf-8")


class CSVRenderer(_FileRenderer):
    format = "csv"


class XLSXRenderer(_FileRenderer):
    format = "xlsx"


def max_export_rows() -> int:
    return int(getattr(settings, "KARNI_EXPORT_MAX_ROWS", 100_000))


class _Resolver:
    """Primary key → natural-key value for one relation column, chunk by chunk.

    Only rows the requester may read are named by their natural key
    (:func:`karni.api.related.related_scope` of the serializer context); any
    other stays its primary key, which is what the API itself shows for it.
    """

    def __init__(self, spec: ColumnSpec, context: Any = None) -> None:
        from django.apps import apps

        self.spec = spec
        self.context = context
        self.model = apps.get_model(spec.target) if spec.target else None
        self.cache: dict[str, Any] = {}
        self.loaded: set[str] = set()

    def load(self, pks: set[Any]) -> None:
        from karni.api.related import related_scope

        if self.model is None or self.spec.lookup is None:
            return
        missing = {pk for pk in pks if str(pk) not in self.loaded}
        if not missing:
            return
        self.loaded.update(str(pk) for pk in missing)
        rows = self.model._base_manager.filter(pk__in=missing)
        scope = related_scope(self.context)
        if scope is not None:
            rows, _filtered = scope(rows)
        for pk, value in rows.values_list("pk", self.spec.lookup):
            self.cache[str(pk)] = value

    def value(self, pk: Any) -> Any:
        if pk is None:
            return ""
        if self.spec.lookup is None:
            return pk
        return self.cache.get(str(pk), pk)


def _key(value: Any) -> Any:
    """A relation's key as the serializer rendered it.

    A nested row (``?expand=``, a nested serializer) is a dict and comes back to
    its ``id``, so it exports by natural key like a plain relation; a nested row
    without an ``id`` cannot be named and exports blank. A key stays a key.
    """
    if isinstance(value, dict):
        return value.get("id")
    return value


def export_rows(
    queryset: QuerySet[Any],
    serializer_class: type[serializers.BaseSerializer[Any]],
    context: dict[str, Any],
    specs: Sequence[ColumnSpec] | None = None,
) -> Iterator[list[Any]]:
    """The header row, then one row per object, as plain values."""
    probe = serializer_class(context=context)
    model: type[Model] = queryset.model
    columns = list(specs) if specs is not None else exportable(column_specs(model, probe))
    yield [spec.name for spec in columns]
    resolvers = {
        spec.name: _Resolver(spec, context)
        for spec in columns
        if spec.kind in ("relation", "relations")
    }
    buffer: list[Any] = []

    def flush() -> Iterator[list[Any]]:
        if not buffer:
            return
        rendered = serializer_class(buffer, many=True, context=context).data
        for name, resolver in resolvers.items():
            pks: set[Any] = set()
            for item in rendered:
                value = item.get(name)
                if isinstance(value, list):
                    pks.update(k for v in value if (k := _key(v)) is not None)
                elif (key := _key(value)) is not None:
                    pks.add(key)
            resolver.load(pks)
        for item in rendered:
            row: list[Any] = []
            for spec in columns:
                value = item.get(spec.name)
                named = resolvers.get(spec.name)
                if named is not None:
                    if isinstance(value, list):
                        value = [named.value(_key(v)) for v in value]
                    else:
                        value = named.value(_key(value))
                row.append(value)
            yield row
        buffer.clear()

    for obj in queryset.iterator(chunk_size=CHUNK):
        buffer.append(obj)
        if len(buffer) >= CHUNK:
            yield from flush()
    yield from flush()


def export_response(
    queryset: QuerySet[Any],
    serializer_class: type[serializers.BaseSerializer[Any]],
    context: dict[str, Any],
    *,
    fmt: str | None = None,
    filename: str | None = None,
    specs: Sequence[ColumnSpec] | None = None,
) -> HttpResponse:
    """A download of ``queryset`` as ``fmt`` (csv by default); ``KARNI_EXPORT_MAX_ROWS`` caps it."""
    fmt = detect_format(None, None, fmt or "csv")
    cap = max_export_rows()
    total = queryset.count()
    if total > cap:
        raise KarniValueError(
            f"This export would have {total} rows; the limit is {cap} (KARNI_EXPORT_MAX_ROWS). "
            "Narrow the filters or export in parts.",
            code="E803",
        )
    stem = filename or str(queryset.model._meta.verbose_name_plural).replace(" ", "-")
    rows = export_rows(queryset, serializer_class, context, specs)
    if fmt == "xlsx":
        response: HttpResponse = HttpResponse(
            xlsx_bytes([(str(queryset.model._meta.verbose_name_plural)[:31], rows)]),
            content_type=CONTENT_TYPES["xlsx"],
        )
    else:
        response = StreamingHttpResponse(csv_lines(rows), content_type=CONTENT_TYPES["csv"])
    response["Content-Disposition"] = f'attachment; filename="{stem}.{fmt}"'
    response["X-Karni-Export-Rows"] = str(total)
    return response
