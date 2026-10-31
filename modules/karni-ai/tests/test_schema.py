"""The schema: from the resource's OpenAPI request component, for the user's role; validation."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from karni_ai.exceptions import ExtractionRefused
from karni_ai.extraction import Extractor
from karni_ai.schema import ResourceSchema, validate_rows
from tests.conftest import make_user


def schema_for(user: Any, resource: str = "products") -> ResourceSchema:
    request = Request(APIRequestFactory().post("/api/ai/extract/"))
    request.user = user
    extractor = Extractor(request)
    view = extractor.target(resource)
    return extractor.schema_for(view, resource, extractor.check_access(view))


def test_the_row_schema_is_the_writable_fields_of_the_request_component(editor: Any) -> None:
    schema = schema_for(editor)
    assert schema.component == "TestappProductRequest"
    assert schema.fields == (
        "name",
        "sku",
        "price",
        "stock",
        "status",
        "released_on",
        "category",
        "tags",
    )
    row = schema.row
    assert row["additionalProperties"] is False and row["required"] == ["name", "price", "sku"]
    properties = row["properties"]
    assert properties["name"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 120,
        "title": "Name",
    }
    assert properties["sku"]["description"] == "The stock keeping unit."
    assert properties["price"]["format"] == "decimal" and "pattern" in properties["price"]
    assert properties["status"]["enum"] == ["draft", "active", "archived"]
    assert properties["released_on"] == {"type": "string", "format": "date", "title": "Released on"}
    assert properties["category"] == {
        "type": "string",
        "title": "Category",
        "description": "The name of a category, exactly as the source writes it.",
    }
    assert properties["tags"]["type"] == "array" and properties["tags"]["items"] == {
        "type": "string"
    }
    assert schema.relations == {
        "category": ("testapp.category", "name"),
        "tags": ("testapp.tag", "name"),
    }
    # No OpenAPI-only keyword reaches the model.
    text = repr(row)
    assert "nullable" not in text and "readOnly" not in text and "x-karni" not in text


def test_left_out_a_file_json_and_a_relation_without_a_natural_key(editor: Any) -> None:
    properties = schema_for(editor).row["properties"]
    assert not {"manual", "specs", "supplier", "id", "created_at"} & set(properties)


def test_a_field_the_role_may_not_write_is_left_out(editor: Any) -> None:
    assert "featured" not in schema_for(editor).fields
    chief = make_user("chief@example.com", "editor", "staff")
    assert "featured" in schema_for(chief).fields


def test_the_document_wraps_rows(editor: Any) -> None:
    document = schema_for(editor).document()
    assert document["required"] == ["rows"] and document["additionalProperties"] is False
    assert document["properties"]["rows"]["items"]["title"] == "product"


def test_a_resource_with_nothing_to_fill(editor: Any, monkeypatch: Any) -> None:
    from karni_ai import schema as schema_module

    monkeypatch.setattr(schema_module, "FILLED_KINDS", frozenset({"nothing"}))
    with pytest.raises(ExtractionRefused) as exc:
        schema_for(editor)
    assert exc.value.code == "AI015"


# validation


@pytest.fixture
def product_schema(editor: Any) -> ResourceSchema:
    return schema_for(editor)


def test_valid_rows_pass_untouched(product_schema: ResourceSchema) -> None:
    answer = {"rows": [{"name": "Hose", "sku": "H-1", "price": "9.50", "stock": 3}]}
    assert validate_rows(product_schema, answer, 50) == (answer["rows"], [])


@pytest.mark.parametrize(
    ("value", "field", "message"),
    [
        ({"stock": "many"}, "stock", "Expected integer, got text."),
        ({"stock": -1}, "stock", "-1 is below the minimum 0."),
        ({"name": "x" * 121}, "name", "Longer than 120 characters."),
        ({"name": ""}, "name", "Empty."),
        ({"price": "9,50"}, "price", "'9,50' is not in the expected form."),
        (
            {"status": "Active"},
            "status",
            "'Active' is not one of the choices: draft, active, archived.",
        ),
        ({"released_on": "31/01/2026"}, "released_on", "'31/01/2026' is not a valid date."),
        ({"tags": "outdoor"}, "tags", "Expected array, got text."),
        ({"colour": "green"}, "colour", "Product has no field 'colour'."),
    ],
)
def test_a_value_that_does_not_fit_is_left_out_with_a_problem(
    product_schema: ResourceSchema, value: dict[str, Any], field: str, message: str
) -> None:
    row = {"name": "Hose", "sku": "H-1", **value}
    checked = validate_rows(product_schema, {"rows": [row]}, 50)
    assert checked is not None
    rows, problems = checked
    assert [(p.row, p.field, p.message, p.source) for p in problems] == [
        (1, field, message, "schema")
    ]
    assert field not in rows[0] and rows[0]["sku"] == "H-1"


def test_nulls_are_not_in_the_source(product_schema: ResourceSchema) -> None:
    checked = validate_rows(product_schema, {"rows": [{"sku": "H-1", "price": None}]}, 50)
    assert checked == ([{"sku": "H-1"}], [])


def test_an_answer_without_rows_is_none(product_schema: ResourceSchema) -> None:
    assert validate_rows(product_schema, {"items": []}, 50) is None
    assert validate_rows(product_schema, [], 50) is None
    assert validate_rows(product_schema, {"rows": {}}, 50) is None
