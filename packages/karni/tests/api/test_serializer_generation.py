"""``build_serializer``: caching, naming, APIMeta policy, sensitive fields."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from rest_framework import serializers
from rest_framework.relations import PrimaryKeyRelatedField

from karni.api.serializers import (
    KarniManyRelatedField,
    KarniModelSerializer,
    KarniPrimaryKeyRelatedField,
    build_serializer,
    serializer_name,
)
from tests.testapp.models import Event, Venue
from tests.testapp.viewsets import EventViewSet


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    """Class-cache isolation: every test starts and ends with an empty cache."""
    build_serializer.cache_clear()  # type: ignore[attr-defined]
    yield
    build_serializer.cache_clear()  # type: ignore[attr-defined]


def _patch_api_meta(monkeypatch: pytest.MonkeyPatch, model: type[Any], **attrs: Any) -> None:
    meta = type("APIMeta", (), attrs)
    monkeypatch.setattr(model, "APIMeta", meta, raising=False)


# explicit serializer_class always wins


class ExplicitEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title"]


def test_explicit_serializer_class_overrides_generation() -> None:
    class ExplicitViewSet(EventViewSet):
        serializer_class = ExplicitEventSerializer

    assert ExplicitViewSet().get_serializer_class() is ExplicitEventSerializer


def test_bare_viewset_generates_a_karni_serializer() -> None:
    generated = EventViewSet().get_serializer_class()
    assert issubclass(generated, KarniModelSerializer)
    assert generated is build_serializer(Event)


# caching (B1)


def test_top_level_builds_are_cached_per_model_expand_and_depth() -> None:
    assert build_serializer(Event) is build_serializer(Event)
    assert build_serializer(Event) is not build_serializer(Venue)
    expanded = build_serializer(Event, expand=frozenset({"venue"}))
    assert expanded is build_serializer(Event, expand=frozenset({"venue"}))
    assert expanded is not build_serializer(Event)
    assert build_serializer(Event, max_depth=3) is not build_serializer(Event)


def test_cache_clear_is_public_and_forces_a_rebuild() -> None:
    before = build_serializer(Event)
    build_serializer.cache_clear()  # type: ignore[attr-defined]
    after = build_serializer(Event)
    assert after is not before
    assert after.__name__ == before.__name__


def test_nested_guard_builds_are_never_cached() -> None:
    first = build_serializer(Event, _seen=(Venue,))
    second = build_serializer(Event, _seen=(Venue,))
    assert first is not second


def test_changing_the_depth_setting_resets_the_cache() -> None:
    before = build_serializer(Event)
    assert before is build_serializer(Event)
    with override_settings(KARNI_API_MAX_EXPAND_DEPTH=3):
        inside = build_serializer(Event)
        assert inside is build_serializer(Event)
        assert inside is not before
    assert build_serializer(Event) is not inside


# naming (B2)


def test_base_name_is_app_qualified() -> None:
    assert serializer_name(Event) == "TestappEventSerializer"
    assert build_serializer(Event).__name__ == "TestappEventSerializer"


def test_expanded_variant_names_are_deterministic() -> None:
    name = serializer_name(Event, frozenset({"venue", "organizer"}))
    assert name == "TestappEvent_Organizer_VenueExpandedSerializer"
    assert serializer_name(Event, frozenset({"venue"})) == ("TestappEvent_VenueExpandedSerializer")


def test_dotted_paths_and_separate_keys_never_collide() -> None:
    two_keys = serializer_name(Event, frozenset({"a", "b"}))
    one_path = serializer_name(Event, frozenset({"a.b"}))
    assert two_keys != one_path
    assert two_keys == "TestappEvent_A_BExpandedSerializer"
    assert one_path == "TestappEvent_ABExpandedSerializer"


def test_schema_name_replaces_the_stem(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_api_meta(monkeypatch, Venue, schema_name="Location")
    assert serializer_name(Venue) == "LocationSerializer"
    assert serializer_name(Venue, frozenset({"x"})) == "Location_XExpandedSerializer"
    assert build_serializer(Venue).__name__ == "LocationSerializer"


# field policy


def test_base_model_fields_are_always_read_only() -> None:
    fields = build_serializer(Event)().fields
    for name in ("id", "created_at", "updated_at", "created_by", "updated_by"):
        assert fields[name].read_only, name
    # Soft-delete state is server-side only: never part of the generated surface.
    assert "deleted_at" not in fields


def test_api_meta_read_only_and_write_only_are_honoured() -> None:
    fields = build_serializer(Event)().fields
    assert fields["status"].read_only
    assert fields["internal_note"].write_only


def test_relations_are_writable_karni_pk_fields_by_default() -> None:
    fields = build_serializer(Event)().fields
    assert isinstance(fields["venue"], KarniPrimaryKeyRelatedField)
    assert not fields["venue"].read_only
    assert isinstance(fields["organizer"], KarniPrimaryKeyRelatedField)
    # M2M stays writable by default (B10); the hatch is APIMeta.read_only.
    assert isinstance(fields["tags"], KarniManyRelatedField)
    assert not fields["tags"].read_only
    assert isinstance(fields["tags"].child_relation, KarniPrimaryKeyRelatedField)


def test_expanded_relations_become_read_only_nested_serializers() -> None:
    fields = build_serializer(Event, expand=frozenset({"venue"}))().fields
    assert isinstance(fields["venue"], serializers.ModelSerializer)
    assert fields["venue"].read_only
    # Every BaseModel carries the audit FKs (read-only); deleted_at never surfaces.
    assert set(fields["venue"].fields) == {
        "id",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "name",
        "city",
    }


def test_user_serializer_matches_the_accounts_contract() -> None:
    """A14: the user model's APIMeta pins the exposed surface exactly."""
    fields = build_serializer(get_user_model())().fields
    assert set(fields) == {
        "id",
        "email",
        "first_name",
        "last_name",
        "email_verified",
        "date_joined",
        "created_at",
        "updated_at",
    }
    for name in ("id", "email", "email_verified", "date_joined", "created_at", "updated_at"):
        assert fields[name].read_only, name
    for name in ("first_name", "last_name"):
        assert not fields[name].read_only, name


def test_password_is_stripped_even_from_explicit_user_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_model = get_user_model()
    _patch_api_meta(monkeypatch, user_model, fields=["id", "email", "password", "is_staff"])
    fields = build_serializer(user_model)().fields
    assert "password" not in fields
    assert fields["is_staff"].read_only  # forced read-only on user models (B5)


# APIMeta validation (B10)


def test_fields_and_exclude_are_mutually_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_api_meta(monkeypatch, Venue, fields=["id", "name"], exclude=["city"])
    with pytest.raises(ImproperlyConfigured, match="Venue"):
        build_serializer(Venue)


def test_read_only_outside_the_field_set_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_api_meta(monkeypatch, Venue, fields=["id", "name"], read_only=["city"])
    with pytest.raises(ImproperlyConfigured, match="Venue.*city"):
        build_serializer(Venue)


def test_write_only_outside_the_field_set_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_api_meta(monkeypatch, Venue, exclude=["city"], write_only=["city"])
    with pytest.raises(ImproperlyConfigured, match="Venue.*city"):
        build_serializer(Venue)


def test_exclude_removes_fields_from_the_default_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_api_meta(monkeypatch, Venue, exclude=["city"])
    fields = build_serializer(Venue)().fields
    assert "city" not in fields
    assert "name" in fields


# recursion and depth


def test_two_level_nesting_recurses_through_related_models() -> None:
    built = build_serializer(Group, expand=frozenset({"permissions.content_type"}))
    permissions = built().fields["permissions"]
    assert isinstance(permissions, serializers.ListSerializer)  # to-many nests as a list
    child = permissions.child
    assert isinstance(child, serializers.ModelSerializer)
    assert isinstance(child.fields["content_type"], serializers.ModelSerializer)


def test_depth_limit_truncates_nesting_at_the_primary_key() -> None:
    built = build_serializer(Group, expand=frozenset({"permissions.content_type"}), max_depth=1)
    child = built().fields["permissions"].child  # type: ignore[union-attr]
    assert isinstance(child.fields["content_type"], PrimaryKeyRelatedField)
    assert not isinstance(child.fields["content_type"], serializers.BaseSerializer)
