"""Choice enums in the OpenAPI schema: named by model and field when a field name collides.

drf-spectacular names a colliding ``status`` enum after its component
(``NovelDetailStatusEnum``) or after a hash of its choices
(``Status469Enum``) once the choice set appears in two components. Karni's
``postprocess_schema_enums`` hook names it after the model and the field
(``NovelStatusEnum``, ``EventStatusEnum``) instead, and a project's
``ENUM_NAME_OVERRIDES`` still wins. Each test builds a small URLconf over
real test models so it controls exactly which fields collide.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from django.urls import URLPattern, path
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.plumbing import _load_enum_name_overrides
from drf_spectacular.settings import patched_settings
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tests.lifecycleapp.models import Ticket as LifecycleTicket
from tests.perfapp.models import Novel, Specimen
from tests.testapp.models import Event, Ticket, Venue

STOCK_HOOK = "drf_spectacular.hooks.postprocess_schema_enums"
COLLISION = "non-optimally resolvable collision"
HASHED = re.compile(r"^Status[0-9A-Za-z]{3}Enum$")


# serializers and views


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title", "status"]


class EventCardSerializer(serializers.ModelSerializer):
    """A second component carrying Event's choice set: drf-spectacular hashes it."""

    class Meta:
        model = Event
        fields = ["id", "status"]


class NovelDetailSerializer(serializers.ModelSerializer):
    """Component ``NovelDetail``, model ``Novel``: the enum takes the model's name."""

    class Meta:
        model = Novel
        fields = ["id", "title", "status"]


class SpecimenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Specimen
        fields = ["id", "size"]


class VenueSerializer(serializers.ModelSerializer):
    """Venue exposes Event's exact choice set under the same field name."""

    status = serializers.ChoiceField(choices=Event.Status.choices, read_only=True)

    class Meta:
        model = Venue
        fields = ["id", "name", "status"]


class TicketSerializer(serializers.ModelSerializer):
    """``testapp.Ticket``: same model name as ``lifecycleapp.Ticket``."""

    status = serializers.ChoiceField(choices=[("new", "New"), ("sold", "Sold")], read_only=True)

    class Meta:
        model = Ticket
        fields = ["id", "subject", "status"]


class LifecycleTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = LifecycleTicket
        fields = ["id", "status"]


class ReportSerializer(serializers.Serializer):
    """No model behind it: the component name stands in."""

    status = serializers.ChoiceField(choices=[("open", "Open"), ("done", "Done")])


class NovelDigestSerializer(serializers.Serializer):
    """No model, but Novel's choice set: the model's name wins."""

    status = serializers.ChoiceField(choices=Novel.Status.choices)


class EventFeedSerializer(serializers.Serializer):
    """``event_status`` is used once, so it keeps the plain ``EventStatusEnum``."""

    event_status = serializers.ChoiceField(choices=[("live", "Live"), ("over", "Over")])


def _detail(serializer: type[serializers.BaseSerializer], model: Any) -> Any:
    view: Any = type(
        f"{serializer.__name__}View",
        (generics.RetrieveUpdateAPIView,),
        {"serializer_class": serializer, "queryset": model.objects.all()},
    )
    return view.as_view()


def _plain(serializer: type[serializers.BaseSerializer]) -> Any:
    class PlainView(APIView):
        @extend_schema(responses=serializer)
        def get(self, request: Request) -> Response:
            return Response()

    PlainView.__name__ = f"{serializer.__name__}View"
    return PlainView.as_view()


EVENT = path("events/<int:pk>/", _detail(EventSerializer, Event))
EVENT_CARD = path("cards/<int:pk>/", _detail(EventCardSerializer, Event))
NOVEL = path("novels/<int:pk>/", _detail(NovelDetailSerializer, Novel))
SPECIMEN = path("specimens/<int:pk>/", _detail(SpecimenSerializer, Specimen))
VENUE = path("venues/<int:pk>/", _detail(VenueSerializer, Venue))
TICKET = path("tickets/<int:pk>/", _detail(TicketSerializer, Ticket))
LIFECYCLE_TICKET = path("cases/<int:pk>/", _detail(LifecycleTicketSerializer, LifecycleTicket))
REPORT = path("report/", _plain(ReportSerializer))
NOVEL_DIGEST = path("digest/", _plain(NovelDigestSerializer))
EVENT_FEED = path("feed/", _plain(EventFeedSerializer))


@pytest.fixture(autouse=True)
def _fresh_overrides() -> Iterator[None]:
    """drf-spectacular caches ENUM_NAME_OVERRIDES per language: clear it around each test."""
    _load_enum_name_overrides.cache_clear()
    yield
    _load_enum_name_overrides.cache_clear()


def _generate(*patterns: URLPattern, **patches: Any) -> tuple[dict[str, Any], list[str]]:
    """The schema over ``patterns`` with spectacular settings patched, and its warnings."""
    GENERATOR_STATS.reset()
    try:
        with patched_settings(patches), GENERATOR_STATS.silence():
            schema = SchemaGenerator(patterns=list(patterns)).get_schema(request=None, public=True)
        messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    finally:
        GENERATOR_STATS.reset()
    return schema, messages


def _enums(schema: dict[str, Any]) -> set[str]:
    return {name for name in schema["components"]["schemas"] if name.endswith("Enum")}


def _enum_of(schema: dict[str, Any], component: str, prop: str = "status") -> str:
    """The enum component ``component.prop`` points at."""
    node = schema["components"]["schemas"][component]["properties"][prop]
    ref = node.get("$ref") or (node.get("allOf") or node.get("oneOf"))[0]["$ref"]
    return str(ref).rsplit("/", 1)[-1]


# collisions


def test_colliding_fields_are_named_by_model_and_field() -> None:
    schema, messages = _generate(EVENT, EVENT_CARD, NOVEL)

    assert _enums(schema) == {"EventStatusEnum", "NovelStatusEnum"}
    for component in ("Event", "EventRequest", "PatchedEventRequest", "EventCard"):
        assert _enum_of(schema, component) == "EventStatusEnum"
    for component in ("NovelDetail", "NovelDetailRequest", "PatchedNovelDetailRequest"):
        assert _enum_of(schema, component) == "NovelStatusEnum"
    enums = schema["components"]["schemas"]
    assert enums["EventStatusEnum"]["enum"] == ["draft", "published"]
    assert enums["NovelStatusEnum"]["enum"] == ["draft", "out"]
    assert not [message for message in messages if COLLISION in message]


def test_drf_spectacular_alone_names_the_same_collision_with_a_hash() -> None:
    # The escape hatch back to drf-spectacular's naming, and the problem Karni fixes.
    schema, messages = _generate(EVENT, EVENT_CARD, NOVEL, POSTPROCESSING_HOOKS=[STOCK_HOOK])

    hashed = [name for name in _enums(schema) if HASHED.match(name)]
    assert len(hashed) == 1
    assert _enum_of(schema, "Event") == hashed[0]
    assert _enum_of(schema, "EventCard") == hashed[0]
    assert _enum_of(schema, "NovelDetail") == "NovelDetailStatusEnum"
    assert [message for message in messages if COLLISION in message]


def test_a_field_name_without_a_collision_keeps_the_plain_name() -> None:
    schema, _messages = _generate(EVENT, EVENT_CARD, SPECIMEN)

    assert _enums(schema) == {"StatusEnum", "SizeEnum"}
    assert _enum_of(schema, "EventCard") == "StatusEnum"


def test_one_choice_set_shared_by_two_models_stays_one_enum() -> None:
    schema, _messages = _generate(EVENT, VENUE, NOVEL)

    assert _enums(schema) == {"EventVenueStatusEnum", "NovelStatusEnum"}
    assert _enum_of(schema, "Event") == "EventVenueStatusEnum"
    assert _enum_of(schema, "Venue") == "EventVenueStatusEnum"
    assert _enum_of(schema, "NovelDetail") == "NovelStatusEnum"


def test_a_serializer_without_a_model_is_named_after_its_component() -> None:
    schema, _messages = _generate(NOVEL, REPORT, NOVEL_DIGEST)

    assert _enums(schema) == {"NovelStatusEnum", "ReportStatusEnum"}
    assert _enum_of(schema, "Report") == "ReportStatusEnum"
    assert _enum_of(schema, "NovelDigest") == "NovelStatusEnum"  # the model's name wins


def test_models_of_the_same_name_get_their_app_label() -> None:
    schema, _messages = _generate(TICKET, LIFECYCLE_TICKET)

    assert _enums(schema) == {"LifecycleappTicketStatusEnum", "TestappTicketStatusEnum"}
    assert _enum_of(schema, "Ticket") == "TestappTicketStatusEnum"
    assert _enum_of(schema, "LifecycleTicket") == "LifecycleappTicketStatusEnum"


def test_a_name_already_in_use_is_never_taken() -> None:
    # EventFeed.event_status is the only `event_status`: plain EventStatusEnum.
    schema, _messages = _generate(EVENT, EVENT_CARD, NOVEL, EVENT_FEED)

    assert _enum_of(schema, "EventFeed", "event_status") == "EventStatusEnum"
    assert _enum_of(schema, "Event") == "TestappEventStatusEnum"
    assert _enum_of(schema, "EventCard") == "TestappEventStatusEnum"
    assert _enum_of(schema, "NovelDetail") == "NovelStatusEnum"


def test_naming_is_deterministic() -> None:
    first, _messages = _generate(EVENT, EVENT_CARD, NOVEL, VENUE, TICKET, LIFECYCLE_TICKET)
    second, _messages = _generate(LIFECYCLE_TICKET, TICKET, VENUE, NOVEL, EVENT_CARD, EVENT)

    assert first["components"]["schemas"] == second["components"]["schemas"]


# escape hatch and reporting


def test_a_project_enum_name_override_wins() -> None:
    overrides = {"NovelStateEnum": "tests.perfapp.models.Novel.Status"}
    schema, _messages = _generate(EVENT, EVENT_CARD, NOVEL, ENUM_NAME_OVERRIDES=overrides)

    assert _enums(schema) == {"EventStatusEnum", "NovelStateEnum"}
    assert _enum_of(schema, "NovelDetail") == "NovelStateEnum"
    assert _enum_of(schema, "Event") == "EventStatusEnum"


def test_an_override_naming_both_sides_of_a_collision_wins_for_both() -> None:
    overrides = {
        "PublicationEnum": Event.Status,
        "NovelPhaseEnum": Novel.Status.choices,
    }
    schema, _messages = _generate(EVENT, EVENT_CARD, NOVEL, ENUM_NAME_OVERRIDES=overrides)

    assert _enums(schema) == {"PublicationEnum", "NovelPhaseEnum"}


def test_other_spectacular_warnings_are_still_printed(capsys: pytest.CaptureFixture[str]) -> None:
    overrides = {"MissingEnum": "tests.nowhere.Choices"}
    GENERATOR_STATS.reset()
    try:
        with patched_settings({"ENUM_NAME_OVERRIDES": overrides}):
            schema = SchemaGenerator(patterns=[EVENT, EVENT_CARD, NOVEL]).get_schema(
                request=None, public=True
            )
        warnings = list(GENERATOR_STATS._warn_cache)
    finally:
        GENERATOR_STATS.reset()

    printed = capsys.readouterr().err
    assert "unable to load choice override for MissingEnum" in printed
    assert any("MissingEnum" in message for message in warnings)
    assert COLLISION not in printed
    assert not [message for message in warnings if COLLISION in message]
    assert _enum_of(schema, "Event") == "EventStatusEnum"
