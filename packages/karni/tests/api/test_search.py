"""Search pipeline: SimpleSearchProvider end-to-end, provider swap, rank_order."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from django.core.cache import cache
from django.db import connection
from django.db.models import QuerySet
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from karni.api.search import SearchProvider, get_search_provider
from karni.api.search.simple import SimpleSearchProvider
from karni.api.viewsets import BaseViewSet
from tests.testapp.models import Event, Venue
from tests.testapp.viewsets import EventViewSet

pytestmark = pytest.mark.django_db

SIMPLE_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
POSTGRES_PROVIDER = "karni.api.search.postgres.PostgresSearchProvider"


class _RecordingProvider(SearchProvider):
    """Captures every call so tests can assert the exact provider contract."""

    calls: ClassVar[list[dict[str, Any]]] = []

    def search(
        self,
        *,
        queryset: QuerySet[Any],
        query: str,
        fields: Any,
        view: Any | None = None,
        rank_order: bool = True,
    ) -> QuerySet[Any]:
        type(self).calls.append(
            {"query": query, "fields": tuple(fields), "view": view, "rank_order": rank_order}
        )
        return queryset.filter(title__istartswith=query)


@pytest.fixture(autouse=True)
def _simple_provider(settings: Any) -> Any:
    """Pin the provider these tests assume, independent of tests/settings.py."""
    settings.KARNI_SEARCH_PROVIDER = SIMPLE_PROVIDER
    _RecordingProvider.calls.clear()
    yield
    cache.clear()


def _status_value() -> str:
    return list(Event._meta.get_field("status").choices)[0][0]


def _event(title: str, **kwargs: Any) -> Event:
    kwargs.setdefault("starts_at", timezone.now())
    kwargs.setdefault("status", _status_value())
    return Event.objects.create(title=title, **kwargs)


def _search_ids(query: dict[str, str]) -> set[str]:
    view = EventViewSet.as_view({"get": "list"})
    response = view(APIRequestFactory().get("/", query))
    assert response.status_code == 200, response.data
    return {row["id"] for row in response.data["results"]}


# --- SimpleSearchProvider unit behaviour -------------------------------------


def test_simple_provider_matches_substrings_case_insensitively() -> None:
    match = _event("Summer MUSIC Fest")
    _event("Quiet Reading")
    result = SimpleSearchProvider().search(
        queryset=Event.objects.all(), query="music", fields=["title"]
    )
    assert set(result) == {match}


def test_simple_provider_ors_across_fields() -> None:
    by_name = Venue.objects.create(name="Berlin Arena", city="Rome")
    by_city = Venue.objects.create(name="Alpha Hall", city="Berlin")
    Venue.objects.create(name="Delta Dome", city="Paris")
    result = SimpleSearchProvider().search(
        queryset=Venue.objects.all(), query="berlin", fields=["name", "city"]
    )
    assert set(result) == {by_name, by_city}


def test_simple_provider_noop_on_empty_query_or_fields() -> None:
    queryset = Event.objects.all()
    provider = SimpleSearchProvider()
    assert provider.search(queryset=queryset, query="", fields=["title"]) is queryset
    assert provider.search(queryset=queryset, query="x", fields=()) is queryset


# --- end-to-end through the viewset ------------------------------------------


def test_search_end_to_end_on_declared_search_fields() -> None:
    fest = _event("Summer Music Fest")
    talk = _event("Music Theory Talk")
    _event("Quiet Reading")
    assert _search_ids({"search": "music"}) == {str(fest.pk), str(talk.pk)}


def test_search_term_is_stripped() -> None:
    fest = _event("Summer Music Fest")
    _event("Quiet Reading")
    assert _search_ids({"search": "  music  "}) == {str(fest.pk)}


def test_empty_search_parameter_is_a_noop() -> None:
    _event("One")
    _event("Two")
    assert len(_search_ids({"search": "   "})) == 2


def test_search_is_a_noop_without_search_fields() -> None:
    class BareVenueViewSet(BaseViewSet):
        model = Venue

    Venue.objects.create(name="Berlin Arena", city="Rome")
    Venue.objects.create(name="Alpha Hall", city="Berlin")
    view = BareVenueViewSet.as_view({"get": "list"})
    response = view(APIRequestFactory().get("/", {"search": "berlin"}))
    assert response.status_code == 200
    assert response.data["count"] == 2


# --- provider interface: swap, cache, rank_order ------------------------------


def test_provider_instance_is_cached() -> None:
    assert get_search_provider() is get_search_provider()
    assert isinstance(get_search_provider(), SimpleSearchProvider)


def test_provider_swap_via_override_settings_proves_the_interface() -> None:
    starts = _event("Music Fest")
    contains = _event("Loud Music")
    with override_settings(KARNI_SEARCH_PROVIDER="tests.api.test_search._RecordingProvider"):
        assert isinstance(get_search_provider(), _RecordingProvider)
        # istartswith semantics instead of icontains: only the prefix match.
        assert _search_ids({"search": "music"}) == {str(starts.pk)}
    # Cache reset on exit: back to the simple provider and its semantics.
    assert isinstance(get_search_provider(), SimpleSearchProvider)
    assert _search_ids({"search": "music"}) == {str(starts.pk), str(contains.pk)}


def test_rank_order_true_without_explicit_ordering() -> None:
    _event("Music Fest")
    with override_settings(KARNI_SEARCH_PROVIDER="tests.api.test_search._RecordingProvider"):
        _search_ids({"search": "music"})
    call = _RecordingProvider.calls[-1]
    assert call["rank_order"] is True
    assert call["query"] == "music"
    assert call["fields"] == tuple(EventViewSet.search_fields)
    assert call["view"] is not None


def test_rank_order_false_with_explicit_ordering() -> None:
    _event("Music Fest")
    with override_settings(KARNI_SEARCH_PROVIDER="tests.api.test_search._RecordingProvider"):
        _search_ids({"search": "music", "ordering": "title"})
    assert _RecordingProvider.calls[-1]["rank_order"] is False


# --- behavioural parity across providers (B8) ---------------------------------


@pytest.mark.parametrize(
    "provider_path",
    [
        pytest.param(SIMPLE_PROVIDER, id="simple"),
        pytest.param(
            POSTGRES_PROVIDER,
            id="postgres",
            marks=pytest.mark.skipif(
                connection.vendor != "postgresql",
                reason="PostgresSearchProvider needs a PostgreSQL database (CI job)",
            ),
        ),
    ],
)
def test_whole_word_search_behaviour_across_providers(provider_path: str) -> None:
    """Word-level queries behave identically on both providers.

    (Substring semantics intentionally differ — full-text search stems words —
    so parity is asserted for whole-word matches only.)
    """
    fest = _event("Summer Music Fest")
    talk = _event("Music Theory Talk")
    _event("Quiet Reading")
    with override_settings(KARNI_SEARCH_PROVIDER=provider_path):
        assert _search_ids({"search": "music"}) == {str(fest.pk), str(talk.pk)}
        assert _search_ids({"search": "zzzunmatched"}) == set()
