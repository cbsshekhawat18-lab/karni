"""The JSON Schema an extraction asks for, from the resource's own writable serializer fields.

:func:`resource_schema` reads the request component the OpenAPI document gives
the resource's create body (``TestappProductRequest``), through the same
drf-spectacular inspector ``/api/schema/`` uses, so the schema an agent or a
client sees and the one the model is asked to fill are one description. It
keeps the fields the user may import (the import's own column list, built for
this user's role), and turns them into plain JSON Schema:

* text, number, boolean, date and choice fields keep their type, format,
  choices, lengths, pattern and bounds.
* a relation is the related row's natural key, as the import reads it (``"the
  name of a category"``), a to-many relation a list of them. A relation to a
  model without a natural key is left out: a text never carries row ids.
* files, JSON and other fields are left out.
* ``null`` means "not in the source". A field that is not given is left alone.

:func:`validate_rows` checks an answer against the schema and returns the
rows to preview and a problem per field the schema refuses. The field's
value is then left out, so the preview never sees a value of the wrong type.
Required fields are not checked here: a row that updates an existing one
(matched by its key) needs none, and the preview says what a new row lacks.

Override / escape hatch: subclass :class:`karni_ai.extraction.Extractor` and
override ``schema_for`` to change the schema of one resource.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from django.db.models import Model
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from karni_ai.exceptions import ExtractionRefused

__all__ = ["Problem", "ResourceSchema", "resource_component", "resource_schema", "validate_rows"]

#: The import column kinds an extraction fills.
FILLED_KINDS: Final = frozenset(
    {"text", "integer", "decimal", "boolean", "date", "datetime", "choice", "relation", "relations"}
)
#: OpenAPI keywords that are not JSON Schema, or that an extraction never asks for.
_DROPPED: Final = frozenset({"readOnly", "writeOnly", "nullable", "default", "example"})


@dataclass(frozen=True)
class Problem:
    """Experimental. One thing wrong with one proposed row: its position from 1, the field, why.

    ``source`` is ``"schema"`` (the answer did not fit the schema) or
    ``"preview"`` (the import's dry run refused it).
    """

    row: int
    field: str
    message: str
    source: str = "schema"

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "field": self.field,
            "message": self.message,
            "source": self.source,
        }


@dataclass(frozen=True)
class ResourceSchema:
    """Experimental. What an extraction into one resource asks for.

    ``component`` is the OpenAPI component the fields come from, ``row`` the
    JSON Schema of one row, ``fields`` the row's properties in order (the
    columns of the import file) and ``relations`` each relation field's
    ``(target, lookup)``.
    """

    resource: str
    model: type[Model]
    component: str
    row: dict[str, Any]
    fields: tuple[str, ...]
    relations: dict[str, tuple[str, str]]

    def document(self) -> dict[str, Any]:
        """The answer's schema: ``{"rows": [<row>, ...]}``."""
        plural = str(self.model._meta.verbose_name_plural)
        return {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "description": f"One item per {self.model._meta.verbose_name} the source "
                    f"describes. No item when it describes no {plural}.",
                    "items": self.row,
                }
            },
            "required": ["rows"],
            "additionalProperties": False,
        }


def resource_component(view: Any, prefix: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """``(name, schema, components)`` of the create body ``view`` documents, as in ``/api/schema/``.

    ``view`` is a request-bound instance of the resource's viewset with
    ``action = "create"``. ``components`` holds the other components the
    schema refers to.
    """
    from drf_spectacular.plumbing import ComponentRegistry

    inspector = view.schema
    inspector.registry = ComponentRegistry()
    inspector.method = "POST"
    inspector.path = f"/api/{prefix}/"
    inspector.path_regex = f"^api/{prefix}/$"
    inspector.path_prefix = "/api/"
    serializer = inspector.get_request_serializer()
    component = inspector.resolve_serializer(serializer, "request")
    if component.name is None or not isinstance(component.schema, dict):
        raise ExtractionRefused(
            f"The resource {prefix!r} documents no request body to extract into.", code="AI008"
        )
    components = inspector.registry.build({}).get("schemas", {})
    return str(component.name), component.schema, components


def _plain(schema: Any, components: dict[str, Any], depth: int = 0) -> Any:
    """An OpenAPI schema as JSON Schema: references inlined, OpenAPI-only keywords dropped."""
    if isinstance(schema, list):
        return [_plain(item, components, depth) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        name = str(schema["$ref"]).rsplit("/", 1)[-1]
        if depth > 5 or name not in components:
            return {}
        return _plain(components[name], components, depth + 1)
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _DROPPED or key.startswith("x-"):
            continue
        if key == "enum" and isinstance(value, list):
            value = [item for item in value if item is not None and item != ""]
        out[key] = _plain(value, components, depth)
    return out


def resource_schema(view: Any, prefix: str, specs: Iterable[Any]) -> ResourceSchema:
    """Experimental. The schema of one row of ``prefix``, for the user behind ``view.request``.

    ``specs`` are the import's importable columns for that user
    (:meth:`karni.transfer.imports.Importer.importable`).

    :raises ExtractionRefused: AI015 when no field is left to fill.
    """
    name, component, components = resource_component(view, prefix)
    model = view.get_model() if hasattr(view, "get_model") else view.model
    by_name = {spec.name: spec for spec in specs if spec.writable and spec.kind in FILLED_KINDS}
    properties: dict[str, Any] = {}
    relations: dict[str, tuple[str, str]] = {}
    for field, part in (component.get("properties") or {}).items():
        spec = by_name.get(field)
        if spec is None:
            continue
        label = str(spec.label)
        if spec.kind in ("relation", "relations"):
            if not spec.lookup or not spec.target:
                continue
            target = spec.target.split(".", 1)[-1]
            words = f"The {spec.lookup} of a {target}, exactly as the source writes it."
            if spec.help:
                words = f"{spec.help} {words}"
            item = {"type": "string"}
            properties[field] = (
                {"type": "array", "items": item, "title": label, "description": words}
                if spec.kind == "relations"
                else {**item, "title": label, "description": words}
            )
            relations[field] = (spec.target, spec.lookup)
            continue
        converted = _plain(part, components)
        if not isinstance(converted, dict) or not converted:
            continue
        converted.setdefault("title", label)
        properties[field] = converted
    if not properties:
        raise ExtractionRefused(
            f"{model.__name__} has no field an extraction can fill for you: text, numbers, "
            "dates, choices, booleans, and relations to a model with a natural key.",
            code="AI015",
        )
    required = [field for field in component.get("required") or () if field in properties]
    row: dict[str, Any] = {
        "type": "object",
        "title": str(model._meta.verbose_name),
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        row["required"] = required
    return ResourceSchema(
        resource=prefix,
        model=model,
        component=name,
        row=row,
        fields=tuple(properties),
        relations=relations,
    )


# validation


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, int | float):
        return "a number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "an object"
    return type(value).__name__


def _message(error: ValidationError) -> str:
    """A field problem in plain words."""
    keyword, expected, value = error.validator, error.validator_value, error.instance
    if keyword == "type":
        wanted = expected if isinstance(expected, str) else " or ".join(map(str, expected))
        return f"Expected {wanted}, got {_kind(value)}."
    if keyword == "enum":
        return f"{value!r} is not one of the choices: {', '.join(map(str, expected))}."
    if keyword == "maxLength":
        return f"Longer than {expected} characters."
    if keyword == "minLength":
        return "Empty."
    if keyword == "pattern":
        return f"{value!r} is not in the expected form."
    if keyword == "format":
        return f"{value!r} is not a valid {expected}."
    if keyword in ("minimum", "exclusiveMinimum"):
        return f"{value!r} is below the minimum {expected}."
    if keyword in ("maximum", "exclusiveMaximum"):
        return f"{value!r} is above the maximum {expected}."
    return str(error.message)


def validate_rows(
    schema: ResourceSchema, answer: Any, max_rows: int
) -> tuple[list[dict[str, Any]], list[Problem]] | None:
    """Experimental. The rows an answer proposes and the problems the schema finds.

    ``None`` when the answer is not ``{"rows": [...]}`` at all. Each row keeps
    the values that fit the schema. A value that does not is left out with a
    problem, as is a field the resource does not have. ``null`` and missing
    values are dropped silently (not in the source). Rows past ``max_rows``
    are left out with one problem.
    """
    if not isinstance(answer, dict) or not isinstance(answer.get("rows"), list):
        return None
    checked = {key: value for key, value in schema.row.items() if key != "required"}
    validator = Draft202012Validator(checked, format_checker=Draft202012Validator.FORMAT_CHECKER)
    items = answer["rows"]
    rows: list[dict[str, Any]] = []
    problems: list[Problem] = []
    for position, item in enumerate(items[:max_rows], start=1):
        if not isinstance(item, dict):
            problems.append(Problem(position, "", f"Not a record ({_kind(item)})."))
            rows.append({})
            continue
        row = {key: value for key, value in item.items() if value is not None}
        for key in [key for key in row if key not in schema.row["properties"]]:
            problems.append(
                Problem(position, key, f"{schema.model.__name__} has no field {key!r}.")
            )
            row.pop(key)
        refused: set[str] = set()
        for error in sorted(validator.iter_errors(row), key=lambda e: list(e.path)):
            field = str(error.path[0]) if error.path else ""
            if field in refused:
                continue
            refused.add(field)
            problems.append(Problem(position, field, _message(error)))
        rows.append({key: value for key, value in row.items() if key not in refused})
    if len(items) > max_rows:
        problems.append(
            Problem(
                max_rows + 1,
                "",
                f"{len(items) - max_rows} more rows were left out: at most {max_rows} are "
                "proposed at once (KARNI_AI_MAX_ROWS).",
            )
        )
    return rows, problems
