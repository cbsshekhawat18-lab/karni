"""The downloadable template: the right headers, one example row, every allowed value."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.db.models import Model
from django.http import HttpResponse

from karni.transfer.fields import ColumnSpec
from karni.transfer.formats import CONTENT_TYPES, csv_lines, detect_format, xlsx_bytes

__all__ = ["template_response", "template_rows"]


def template_rows(specs: Sequence[ColumnSpec]) -> tuple[list[list[Any]], list[list[Any]]]:
    """``(data rows, allowed-value rows)``: headers + an example; field/value/label triples."""
    data = [[spec.name for spec in specs], [spec.example for spec in specs]]
    allowed: list[list[Any]] = [["field", "value", "label"]]
    for spec in specs:
        for value, label in spec.choices:
            allowed.append([spec.name, value, label])
        if spec.kind == "boolean":
            allowed.append([spec.name, "true", "yes"])
            allowed.append([spec.name, "false", "no"])
        if spec.kind in ("relation", "relations") and spec.target:
            allowed.append(
                [
                    spec.name,
                    f"<{spec.lookup or 'id'}>",
                    f"the {spec.lookup or 'id'} of a {spec.target}",
                ]
            )
    return data, allowed


def template_response(
    model: type[Model], specs: Sequence[ColumnSpec], fmt: str | None
) -> HttpResponse:
    """The template as a download; XLSX carries the allowed values on a second sheet."""
    fmt = detect_format(None, None, fmt or "xlsx")
    data, allowed = template_rows(specs)
    stem = f"{str(model._meta.verbose_name_plural).replace(' ', '-')}-template"
    if fmt == "xlsx":
        body = xlsx_bytes([("Data", data), ("Allowed values", allowed)])
        response = HttpResponse(body, content_type=CONTENT_TYPES["xlsx"])
    else:
        response = HttpResponse("".join(csv_lines(data)), content_type=CONTENT_TYPES["csv"])
    response["Content-Disposition"] = f'attachment; filename="{stem}.{fmt}"'
    return response
