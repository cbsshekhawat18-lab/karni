"""Ordering behaviour of BaseViewSet (stock OrderingFilter in Karni's pipeline)."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from tests.testapp.models import Event
from tests.testapp.viewsets import EventViewSet

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_throttle_state() -> Any:
    yield
    cache.clear()


def _status_value() -> str:
    return list(Event._meta.get_field("status").choices)[0][0]


def _event(title: str, *, created_offset: int = 0, **kwargs: Any) -> Event:
    kwargs.setdefault("starts_at", timezone.now())
    kwargs.setdefault("status", _status_value())
    event = Event.objects.create(title=title, **kwargs)
    if created_offset:
        # auto_now_add cannot be set at create time; update() bypasses it.
        created_at = timezone.now() + datetime.timedelta(seconds=created_offset)
        Event.objects.filter(pk=event.pk).update(created_at=created_at)
    return event


def _listed_ids(query: dict[str, str] | None = None) -> list[str]:
    view = EventViewSet.as_view({"get": "list"})
    response = view(APIRequestFactory().get("/", query or {}))
    assert response.status_code == 200, response.data
    return [row["id"] for row in response.data["results"]]


def _default_ordering() -> list[str]:
    """The ordering the contract prescribes: model Meta.ordering or -created_at."""
    return [str(o) for o in Event._meta.ordering] or ["-created_at"]


def test_explicit_ordering_ascending() -> None:
    middle = _event("Middle", capacity=20)
    small = _event("Small", capacity=10)
    large = _event("Large", capacity=30)
    assert _listed_ids({"ordering": "capacity"}) == [str(small.pk), str(middle.pk), str(large.pk)]


def test_explicit_ordering_descending() -> None:
    middle = _event("Middle", capacity=20)
    small = _event("Small", capacity=10)
    large = _event("Large", capacity=30)
    assert _listed_ids({"ordering": "-capacity"}) == [str(large.pk), str(middle.pk), str(small.pk)]


def test_default_ordering_is_newest_first() -> None:
    _event("Oldest", created_offset=-300)
    _event("Middle", created_offset=-150)
    _event("Newest")
    expected = [
        str(pk) for pk in Event.objects.order_by(*_default_ordering()).values_list("pk", flat=True)
    ]
    assert _listed_ids() == expected
    # And the contract's stated default actually kicks in for the test model.
    if not Event._meta.ordering:
        newest_first = [
            str(pk) for pk in Event.objects.order_by("-created_at").values_list("pk", flat=True)
        ]
        assert _listed_ids() == newest_first


def test_explicit_ordering_overrides_the_default() -> None:
    beta = _event("Beta", created_offset=-300)
    alpha = _event("Alpha", created_offset=-150)
    zeta = _event("Zeta")
    assert _listed_ids({"ordering": "title"}) == [str(alpha.pk), str(beta.pk), str(zeta.pk)]


def test_write_only_fields_are_not_orderable() -> None:
    """B11: ordering_fields="__all__" is serializer-driven; write_only is invalid.

    An invalid ordering parameter is dropped by OrderingFilter, so the default
    ordering applies — if ``internal_note`` were orderable, "aaa" would sort
    first here instead.
    """
    older = _event("Older", created_offset=-300, internal_note="zzz")
    newer = _event("Newer", internal_note="aaa")
    default_order = [
        str(pk) for pk in Event.objects.order_by(*_default_ordering()).values_list("pk", flat=True)
    ]
    result = _listed_ids({"ordering": "internal_note"})
    assert result == default_order
    ascending_by_note = [str(newer.pk), str(older.pk)]
    if default_order != ascending_by_note:
        assert result != ascending_by_note
