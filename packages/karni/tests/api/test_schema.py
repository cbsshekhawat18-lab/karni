"""Generated OpenAPI schema: fidelity, Karni params and vendor extensions.

The schema is produced once per module through drf-spectacular's
``SchemaGenerator`` over the real test URLconf, with drf-spectacular's
warning/error sink captured so regressions in Karni's own endpoints fail
loudly (B4/B13).
"""

from __future__ import annotations

from typing import Any

import pytest
from django.conf import settings as django_settings
from django.test import override_settings
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator

from karni.api.routers import KarniRouter
from tests.testapp.viewsets import EventViewSet, TagViewSet

KARNI_MARKERS = (
    "testapp",
    "Testapp",
    "EventViewSet",
    "VenueViewSet",
    "OrganizerViewSet",
    "TagViewSet",
    "karni.api",
)


def _generate() -> tuple[dict[str, Any], list[str]]:
    """Generate the schema, returning it with spectacular's warning messages."""
    GENERATOR_STATS.reset()
    with GENERATOR_STATS.silence():
        schema = SchemaGenerator().get_schema(request=None, public=True)
    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    GENERATOR_STATS.reset()
    return schema, messages


@pytest.fixture(scope="module")
def generated() -> tuple[dict[str, Any], list[str]]:
    return _generate()


@pytest.fixture(scope="module")
def schema(generated: tuple[dict[str, Any], list[str]]) -> dict[str, Any]:
    return generated[0]


def _deref(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Resolve ``$ref`` / single-branch ``allOf`` down to a concrete schema."""
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        return _deref(schema, schema["components"]["schemas"][name])
    if "allOf" in node:
        merged: dict[str, Any] = {}
        for part in node["allOf"]:
            merged.update(_deref(schema, part))
        merged.update({key: value for key, value in node.items() if key != "allOf"})
        return merged
    return node


def _component(schema: dict[str, Any], name: str) -> dict[str, Any]:
    return schema["components"]["schemas"][name]


def _params(schema: dict[str, Any], path: str) -> dict[str, dict[str, Any]]:
    operation = schema["paths"][path]["get"]
    return {param["name"]: param for param in operation.get("parameters", [])}


# components


def test_conf_default_schema_class_is_karni() -> None:
    assert (
        django_settings.REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] == "karni.api.schema.KarniAutoSchema"
    )


def test_event_components_exist_with_split_request(schema: dict[str, Any]) -> None:
    components = schema["components"]["schemas"]
    assert "TestappEvent" in components
    assert "TestappEventRequest" in components  # COMPONENT_SPLIT_REQUEST
    assert "PatchedTestappEventRequest" in components


def test_status_is_a_read_only_enum_of_the_two_choices(schema: dict[str, Any]) -> None:
    status = _deref(schema, _component(schema, "TestappEvent")["properties"]["status"])
    assert set(status["enum"]) == {"draft", "published"}
    assert status["type"] == "string"
    assert status.get("readOnly") is True


def test_capacity_is_a_nullable_integer(schema: dict[str, Any]) -> None:
    capacity = _component(schema, "TestappEvent")["properties"]["capacity"]
    # OAS 3.0 spells nullability as `nullable: true`; 3.1 as a type list.
    if isinstance(capacity.get("type"), list):
        assert set(capacity["type"]) >= {"integer", "null"}
    else:
        assert capacity["type"] == "integer"
        assert capacity.get("nullable") is True


def test_title_is_required_in_response_and_request(schema: dict[str, Any]) -> None:
    assert "title" in _component(schema, "TestappEvent")["required"]
    assert "title" in _component(schema, "TestappEventRequest")["required"]
    assert "starts_at" in _component(schema, "TestappEventRequest")["required"]


def test_created_at_is_read_only_date_time(schema: dict[str, Any]) -> None:
    created_at = _component(schema, "TestappEvent")["properties"]["created_at"]
    assert created_at == {"type": "string", "format": "date-time", "readOnly": True}


def test_write_only_field_appears_only_on_the_request_side(schema: dict[str, Any]) -> None:
    assert "internal_note" not in _component(schema, "TestappEvent")["properties"]
    assert "internal_note" in _component(schema, "TestappEventRequest")["properties"]


# operation parameters (B4)


def test_list_operation_documents_the_full_karni_pipeline(schema: dict[str, Any]) -> None:
    params = _params(schema, "/api/events/")
    for name in ("expand", "search", "ordering", "page", "page_size"):
        assert name in params, name
    # Auto-derived filterset parameters surface too (declared lookups).
    for name in ("capacity", "capacity__gte", "capacity__lte", "title__icontains"):
        assert name in params, name


def test_expand_parameter_enumerates_the_allowed_keys(schema: dict[str, Any]) -> None:
    expand = _params(schema, "/api/events/")["expand"]
    assert expand["in"] == "query"
    # `required: false` is the OAS default, so spectacular omits the key.
    assert expand.get("required", False) is False
    assert expand["schema"]["type"] == "array"
    assert expand["schema"]["items"]["enum"] == ["organizer", "tags", "venue"]


def test_expand_is_on_retrieve_too(schema: dict[str, Any]) -> None:
    params = _params(schema, "/api/events/{id}/")
    assert "expand" in params
    assert params["expand"]["schema"]["items"]["enum"] == ["organizer", "tags", "venue"]


def test_no_expand_parameter_without_expandable_relations(schema: dict[str, Any]) -> None:
    assert "expand" not in _params(schema, "/api/venues/")


def test_search_documented_only_where_search_fields_exist(schema: dict[str, Any]) -> None:
    assert "search" in _params(schema, "/api/events/")  # EventViewSet.search_fields
    assert "search" not in _params(schema, "/api/venues/")  # none declared


# vendor extensions (B13)


def test_list_operations_carry_x_karni_resource(schema: dict[str, Any]) -> None:
    assert schema["paths"]["/api/events/"]["get"]["x-karni-resource"] == "events"
    assert schema["paths"]["/api/venues/"]["get"]["x-karni-resource"] == "venues"
    assert "x-karni-resource" not in schema["paths"]["/api/events/{id}/"]["get"]


def test_forward_relations_carry_x_karni_relation(schema: dict[str, Any]) -> None:
    properties = _component(schema, "TestappEvent")["properties"]
    assert properties["venue"]["x-karni-relation"] == {"resource": "venues", "many": False}
    assert properties["organizer"]["x-karni-relation"] == {"resource": "users", "many": False}


def test_relation_extension_is_omitted_without_a_route(schema: dict[str, Any]) -> None:
    # Tag has no registered viewset by default: no extension, no error.
    assert "x-karni-relation" not in _component(schema, "TestappEvent")["properties"]["tags"]


def _labels_router() -> KarniRouter:
    """Router factory registering the (normally unrouted) Tag viewset."""
    router = KarniRouter()
    router.register("labels", TagViewSet, basename="labels")
    router.autodiscover()
    return router


@override_settings(KARNI_API_ROUTER="tests.api.test_schema._labels_router")
def test_to_many_relation_resolves_through_the_configured_router() -> None:
    schema, _messages = _generate()
    tags = _component(schema, "TestappEvent")["properties"]["tags"]
    assert tags["type"] == "array"
    assert tags["x-karni-relation"] == {"resource": "labels", "many": True}


# generation hygiene


def test_no_spectacular_warnings_or_errors_for_karni_endpoints(
    generated: tuple[dict[str, Any], list[str]],
) -> None:
    _schema, messages = generated
    offending = [
        message for message in messages if any(marker in message for marker in KARNI_MARKERS)
    ]
    assert not offending, offending


def test_serializer_resolution_without_a_request_never_fails() -> None:
    """B4: schema time has no real request — resolution must not raise or 400."""
    viewset = EventViewSet()
    serializer_class = viewset.get_serializer_class()
    assert serializer_class.__name__ == "TestappEventSerializer"
