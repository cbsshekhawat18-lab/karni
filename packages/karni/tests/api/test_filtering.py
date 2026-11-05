"""Auto-derived filterset behaviour of :class:`karni.api.filters.KarniFilterBackend`."""

from __future__ import annotations

from typing import Any

import django_filters
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import models
from django.utils import timezone
from django_filters.rest_framework import FilterSet
from rest_framework.test import APIRequestFactory

from karni.api.filters import IntegerFilter, KarniFilterBackend
from tests.testapp.models import TEST_PK, Event, Part, Reading, Stamp, Venue
from tests.testapp.viewsets import EventViewSet

#: The derived filter of a relation to the testapp API models (KARNI_TEST_PK).
TESTAPP_PK_FILTER = django_filters.UUIDFilter if TEST_PK == "uuid" else IntegerFilter


@pytest.fixture(autouse=True)
def _reset_throttle_state() -> Any:
    """Keep DRF's default anon/user throttles from leaking across tests."""
    yield
    cache.clear()


class _OptInView:
    """Plain (non-BaseViewSet) view that opts into auto-derivation."""

    karni_auto_filterset = True
    filterset_class = None
    filterset_fields = None


class _StockView:
    """Plain view without the opt-in: stock DjangoFilterBackend behaviour."""

    filterset_class = None
    filterset_fields = None


def _derived(model: type[models.Model]) -> type[FilterSet]:
    filterset = KarniFilterBackend().get_filterset_class(_OptInView(), model._default_manager.all())
    assert filterset is not None
    return filterset


def _status_value(index: int = 0) -> str:
    choices = list(Event._meta.get_field("status").choices)
    return choices[index][0]


def _event(title: str = "Event", **kwargs: Any) -> Event:
    kwargs.setdefault("starts_at", timezone.now())
    kwargs.setdefault("status", _status_value())
    return Event.objects.create(title=title, **kwargs)


def _result_ids(response: Any) -> set[str]:
    assert response.status_code == 200, response.data
    return {str(row["id"]) for row in response.data["results"]}


# derivation rules (no database needed)


def test_numeric_field_derives_exact_gte_lte_param_names() -> None:
    base = _derived(Event).base_filters
    assert {"capacity", "capacity__gte", "capacity__lte"} <= set(base)


def test_char_field_derives_exact_and_icontains() -> None:
    base = _derived(Event).base_filters
    assert {"title", "title__icontains"} <= set(base)


def test_datetime_field_derives_range_lookups() -> None:
    base = _derived(Event).base_filters
    assert {"starts_at", "starts_at__gte", "starts_at__lte"} <= set(base)


def test_boolean_field_derives_exact_only() -> None:
    base = _derived(Event).base_filters
    assert "is_public" in base
    assert "is_public__gte" not in base


def test_text_field_is_not_derived() -> None:
    base = _derived(Event).base_filters
    assert not any(name.startswith("description") for name in base)


def test_choices_field_uses_choice_filter_with_exact_only() -> None:
    base = _derived(Event).base_filters
    assert isinstance(base["status"], django_filters.ChoiceFilter)
    assert "status__icontains" not in base
    assert "status__gte" not in base
    filter_choices = dict(base["status"].extra["choices"])
    assert filter_choices == dict(Event._meta.get_field("status").choices)


def test_write_only_field_is_not_filterable() -> None:
    base = _derived(Event).base_filters
    assert not any(name.startswith("internal_note") for name in base)


def test_relation_filters_use_target_pk_type_not_model_choice() -> None:
    base = _derived(Event).base_filters
    assert isinstance(base["organizer"], django_filters.UUIDFilter)  # the user model: UUIDs
    assert type(base["venue"]) is TESTAPP_PK_FILTER
    for name in ("venue", "organizer"):
        assert not isinstance(base[name], django_filters.ModelChoiceFilter), name


@pytest.mark.parametrize("model", [Event, Part, Stamp], ids=lambda m: m.__name__)
def test_the_primary_key_gets_no_derived_filter(model: type[models.Model]) -> None:
    """No ?id=, ?id__gte= or ?id__lte=, whatever the key type: integer ranges walk the table."""
    base = _derived(model).base_filters
    assert not any(name == "id" or name.startswith("id__") for name in base), sorted(base)


def test_an_integer_key_relation_filter_takes_whole_numbers_only() -> None:
    base = _derived(Reading).base_filters
    assert type(base["part"]) is IntegerFilter
    filterset = _derived(Reading)
    assert filterset({"part": "12"}, queryset=Reading.objects.none()).is_valid()
    refused = filterset({"part": "1.5"}, queryset=Reading.objects.none())
    assert not refused.is_valid() and "part" in refused.errors


@pytest.mark.django_db
def test_a_declared_id_filter_still_works() -> None:
    class ExplicitView(_OptInView):
        filterset_fields = {"id": ["exact", "gte"]}

    filterset = KarniFilterBackend().get_filterset_class(
        ExplicitView(), Reading._default_manager.all()
    )
    assert filterset is not None and {"id", "id__gte"} <= set(filterset.base_filters)
    low, high = Reading.objects.create(value=1), Reading.objects.create(value=2)
    found = filterset({"id__gte": str(high.pk)}, queryset=Reading.objects.all()).qs
    assert list(found) == [high] and low not in found


def test_m2m_field_is_not_derived() -> None:
    base = _derived(Event).base_filters
    assert "tags" not in base


def test_soft_delete_state_is_not_filterable_but_audit_users_are() -> None:
    """Mirrors the serializer: ``deleted_at`` stays server-side, audit FKs are exposed."""
    base = _derived(Event).base_filters
    assert not any(name.startswith("deleted_at") for name in base)
    for name in ("created_by", "updated_by"):
        assert isinstance(base[name], django_filters.UUIDFilter), name  # the user model


def test_user_model_sensitive_fields_are_not_filterable() -> None:
    """APIMeta restricts the effective set; password is never filterable."""
    base = _derived(get_user_model()).base_filters
    assert "email" in base
    assert not any(name.startswith("password") for name in base)
    assert not any(name.startswith("is_superuser") for name in base)
    assert not any(name.startswith("is_staff") for name in base)


def test_derived_filterset_is_cached_per_model() -> None:
    assert _derived(Event) is _derived(Event)
    assert _derived(Event) is not _derived(Venue)


def test_lookup_map_is_an_overridable_class_attribute() -> None:
    class ExactOnlyBackend(KarniFilterBackend):
        lookup_map = {**KarniFilterBackend.lookup_map, models.CharField: ("exact",)}

    base = ExactOnlyBackend().derive_filterset_class(Event).base_filters
    assert "title" in base
    assert "title__icontains" not in base
    # The subclass keeps its own cache slot; the stock derivation is untouched.
    assert "title__icontains" in _derived(Event).base_filters


def test_explicit_filterset_fields_win_untouched() -> None:
    class ExplicitView(_OptInView):
        filterset_fields = ["is_public"]

    filterset = KarniFilterBackend().get_filterset_class(
        ExplicitView(), Event._default_manager.all()
    )
    assert filterset is not None
    assert set(filterset.base_filters) == {"is_public"}


def test_plain_views_get_stock_django_filter_behaviour() -> None:
    filterset = KarniFilterBackend().get_filterset_class(_StockView(), Event._default_manager.all())
    assert filterset is None


def test_karni_auto_filterset_flag_opts_a_plain_view_in() -> None:
    assert (
        KarniFilterBackend().get_filterset_class(_OptInView(), Event._default_manager.all())
        is not None
    )


def test_base_viewset_subclasses_auto_derive() -> None:
    filterset = KarniFilterBackend().get_filterset_class(
        EventViewSet(), Event._default_manager.all()
    )
    assert filterset is not None
    assert "capacity__gte" in filterset.base_filters


# request-level behaviour


@pytest.mark.django_db
def test_capacity_exact_and_range_filtering() -> None:
    small = _event("Small", capacity=5)
    large = _event("Large", capacity=100)
    _event("Unsized", capacity=None)
    view = EventViewSet.as_view({"get": "list"})
    factory = APIRequestFactory()

    assert _result_ids(view(factory.get("/", {"capacity": "100"}))) == {str(large.pk)}
    assert _result_ids(view(factory.get("/", {"capacity__gte": "50"}))) == {str(large.pk)}
    assert _result_ids(view(factory.get("/", {"capacity__lte": "50"}))) == {str(small.pk)}


@pytest.mark.django_db
def test_choice_filtering_and_invalid_choice_rejected() -> None:
    first = _event("First", status=_status_value(0))
    second = _event("Second", status=_status_value(1))
    view = EventViewSet.as_view({"get": "list"})
    factory = APIRequestFactory()

    assert _result_ids(view(factory.get("/", {"status": _status_value(0)}))) == {str(first.pk)}
    assert _result_ids(view(factory.get("/", {"status": _status_value(1)}))) == {str(second.pk)}
    response = view(factory.get("/", {"status": "definitely-not-a-choice"}))
    assert response.status_code == 400


@pytest.mark.django_db
def test_write_only_query_parameter_is_ignored() -> None:
    kept = _event("Kept", internal_note="alpha")
    other = _event("Other", internal_note="beta")
    view = EventViewSet.as_view({"get": "list"})
    response = view(APIRequestFactory().get("/", {"internal_note": "alpha"}))
    assert _result_ids(response) == {str(kept.pk), str(other.pk)}
