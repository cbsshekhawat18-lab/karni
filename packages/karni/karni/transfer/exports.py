"""Export a queryset as CSV or XLSX — what the user may see, written so it imports back.

Rows are whatever queryset the caller already scoped (a viewset's filtered,
read-scoped queryset; an admin changelist selection); columns are the
serializer's readable fields for this user (``Karni.field_roles`` applied by
the serializer itself). Relations are written as the target's
``Karni.natural_key`` when it has one, else the primary key; to-many
relations join their values with ``|``. CSV streams; XLSX is built in memory
(``KARNI_EXPORT_MAX_ROWS`` caps both).
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
    """Primary key → natural-key value for one relation column, chunk by chunk."""

    def __init__(self, spec: ColumnSpec) -> None:
        from django.apps import apps

        self.spec = spec
        self.model = apps.get_model(spec.target) if spec.target else None
        self.cache: dict[str, Any] = {}

    def load(self, pks: set[Any]) -> None:
        if self.model is None or self.spec.lookup is None:
            return
        missing = {pk for pk in pks if str(pk) not in self.cache}
        if not missing:
            return
        rows = self.model._base_manager.filter(pk__in=missing).values_list("pk", self.spec.lookup)
        for pk, value in rows:
            self.cache[str(pk)] = value

    def value(self, pk: Any) -> Any:
        if pk is None:
            return ""
        if self.spec.lookup is None:
            return pk
        return self.cache.get(str(pk), pk)


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
        spec.name: _Resolver(spec) for spec in columns if spec.kind in ("relation", "relations")
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
                    pks.update(v for v in value if v is not None)
                elif value is not None and not isinstance(value, dict):
                    pks.add(value)
            resolver.load(pks)
        for item in rendered:
            row: list[Any] = []
            for spec in columns:
                value = item.get(spec.name)
                named = resolvers.get(spec.name)
                if named is not None and not isinstance(value, dict):
                    if isinstance(value, list):
                        value = [named.value(v) for v in value]
                    else:
                        value = named.value(value)
                elif isinstance(value, dict) and "id" in value:
                    value = value["id"]  # an expanded relation: back to its key
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
