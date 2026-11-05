"""``x-karni-related`` (experimental): each model's reverse relations in the OpenAPI schema.

``@karni/ui``'s ResourceDetail builds its related tabs from it, so the
schema says, per relation, which resource holds the rows, which field
points back, which list parameter filters by it and which value it takes.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.test import override_settings
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator

from karni.api import Access, Public
from karni.api import schema as schema_mod
from karni.api.routers import KarniRouter
from karni.api.schema import KarniAutoSchema
from karni.api.viewsets import BaseViewSet
from tests.testapp.models import Event
from tests.testapp.viewsets import TagViewSet

ROUTER = "tests.api.test_schema_related"


def _generate() -> dict[str, Any]:
    GENERATOR_STATS.reset()
    with GENERATOR_STATS.silence():
        schema: dict[str, Any] = SchemaGenerator().get_schema(request=None, public=True)
    GENERATOR_STATS.reset()
    return schema


def _related(schema: dict[str, Any], path: str) -> Any:
    return schema["paths"][path]["get"].get("x-karni-related")


def _related_of(viewset: type[BaseViewSet]) -> list[dict[str, Any]]:
    """``get_karni_related`` for a viewset the test URLconf does not route."""
    auto = KarniAutoSchema()
    auto.view = viewset(request=None, format_kwarg=None, action="list", args=(), kwargs={})
    return auto.get_karni_related()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return _generate()


def test_a_list_names_its_reverse_relations_and_their_filter(schema: dict[str, Any]) -> None:
    assert _related(schema, "/api/venues/") == [
        {
            "name": "events",
            "resource": "events",
            "field": "venue",
            "param": "venue",
            "key": "id",
            "label": "Events",
        }
    ]
    assert _related(schema, "/api/users/")[0]["param"] == "organizer"


def test_only_list_operations_carry_it_and_only_where_there_is_one(schema: dict[str, Any]) -> None:
    assert "x-karni-related" not in schema["paths"]["/api/venues/{id}/"]["get"]
    # Event's own relations are forward ones; Tag (its M2M target) has no route.
    assert _related(schema, "/api/events/") is None


def labels_router() -> KarniRouter:
    """Tag routed: Event.tags is a reverse many-to-many relation of a routed model."""
    router = KarniRouter()
    router.register("labels", TagViewSet, basename="labels")
    router.autodiscover()
    return router


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.labels_router")
def test_a_relation_the_list_cannot_filter_by_has_no_param() -> None:
    # The derived filterset leaves many-to-many fields out: no ?tags= on /events/.
    assert _related_of(TagViewSet) == [
        {
            "name": "events",
            "resource": "events",
            "field": "tags",
            "param": None,
            "key": "id",
            "label": "Events",
        }
    ]


class StatusOnlyEvents(BaseViewSet):
    """Events whose list filters by status only (an explicit filterset_fields wins)."""

    model = Event
    access = Access(read=Public(), write=Public())
    filterset_fields = ["status"]


class TagFilteredEvents(BaseViewSet):
    """Events whose list declares a filter on the many-to-many tags field."""

    model = Event
    access = Access(read=Public(), write=Public())
    filterset_fields = {"tags": ["exact"], "venue": ["exact"]}


def status_only_router() -> KarniRouter:
    router = KarniRouter()
    router.register("status-events", StatusOnlyEvents, basename="status-events")
    router.autodiscover()
    return router


def tag_filter_router() -> KarniRouter:
    router = KarniRouter()
    router.register("labels", TagViewSet, basename="labels")
    router.register("tagged-events", TagFilteredEvents, basename="tagged-events")
    router.autodiscover()
    return router


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.status_only_router")
def test_the_param_comes_from_the_filterset_the_list_applies() -> None:
    related = _related(_generate(), "/api/venues/")
    assert related[0]["resource"] == "status-events"
    assert related[0]["param"] is None


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.tag_filter_router")
def test_a_declared_filter_on_a_many_to_many_field_is_the_param() -> None:
    assert _related_of(TagViewSet)[0]["param"] == "tags"
    assert _related(_generate(), "/api/venues/")[0]["param"] == "venue"


def _relation(name: str, field: str, *, many: bool = False, hidden: bool = False) -> Any:
    return SimpleNamespace(
        one_to_many=not many,
        many_to_many=many,
        one_to_one=False,
        hidden=hidden,
        related_model=Event,
        field=SimpleNamespace(
            name=field,
            verbose_name=field.replace("_", " "),
            target_field=SimpleNamespace(name="id"),
        ),
        get_accessor_name=lambda: name,
    )


def test_two_relations_to_one_resource_get_labels_that_tell_them_apart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relations = [
        _relation("events", "venue"),
        _relation("backup_events", "backup_venue"),
        _relation("hidden_events", "other", hidden=True),
    ]
    model = SimpleNamespace(
        _meta=SimpleNamespace(related_objects=relations, pk=SimpleNamespace(name="id"))
    )
    view = SimpleNamespace(get_model=lambda: model, request=None)
    monkeypatch.setattr(KarniAutoSchema, "_karni_view", lambda self: view)
    monkeypatch.setattr(schema_mod, "_registered_route", lambda match: ("events", object))
    monkeypatch.setattr(schema_mod, "_filter_param", lambda viewset, model, field, view: field)
    entries = KarniAutoSchema().get_karni_related()
    assert [(entry["name"], entry["label"], entry["param"]) for entry in entries] == [
        ("events", "Events (venue)", "venue"),
        ("backup_events", "Events (backup venue)", "backup_venue"),
    ]
