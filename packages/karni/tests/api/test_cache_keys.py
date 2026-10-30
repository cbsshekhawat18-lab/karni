"""Response caching keys: the normalised URL and the access scope decide who shares an entry."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, ClassVar

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache as default_cache
from django.db.models import Q
from django.http import QueryDict
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework import serializers
from rest_framework.test import APIRequestFactory, force_authenticate

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.api import Access, BaseViewSet, Cache, Granted, HasRole, Owned, Public, Uncached, Where
from karni.api.caching import access_scope, normalized_query
from tests.testapp.models import Event, Tag, Venue

pytestmark = pytest.mark.django_db

READERS = Access(read=HasRole("reader"), write=HasRole("reader"))


class ReaderEvents(BaseViewSet):
    model = Event
    access = READERS
    auto_register = False


class PublicEvents(BaseViewSet):
    model = Event
    access = Access(read=Public(), write=HasRole("reader"))
    auto_register = False


class GrantedEvents(BaseViewSet):
    model = Event
    access = Granted()
    auto_register = False


class OwnedEvents(BaseViewSet):
    model = Event
    access = Access(read=Owned("organizer"), write=Owned("organizer"))
    auto_register = False


class WhereEvents(BaseViewSet):
    model = Event
    access = Access(read=Where(lambda request: Q(is_public=True)), write=HasRole("reader"))
    auto_register = False


class FilteredEvents(ReaderEvents):
    def get_queryset(self) -> Any:
        return super().get_queryset().filter(is_public=True)


class StarredSerializer(serializers.ModelSerializer):
    starred = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ["id", "title", "starred"]

    def get_starred(self, event: Event) -> bool:
        return bool(event.title.startswith("A"))


class StarredEvents(ReaderEvents):
    serializer_class = StarredSerializer


@pytest.fixture(autouse=True)
def _cache_on() -> Iterator[None]:
    default_cache.clear()
    with override_settings(KARNI_API_CACHE=True):
        yield
    default_cache.clear()


@pytest.fixture
def event() -> Event:
    venue = Venue.objects.create(name="Arena", city="Lyon")
    found = Event.objects.create(title="One", starts_at=timezone.now(), venue=venue)
    found.tags.add(Tag.objects.create(name="music"))
    return found


def _user(email: str, *roles: str, **flags: Any) -> Any:
    user = get_user_model().objects.create_user(email=email, password="pw-123456789", **flags)
    for role in roles:
        assign_role(user, role)
    return user


def _get(
    viewset: type[Any],
    path: str = "/",
    *,
    user: Any = None,
    action: str = "list",
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    extra = {
        f"HTTP_{name.upper().replace('-', '_')}": value for name, value in (headers or {}).items()
    }
    request = APIRequestFactory().get(path, **extra)
    if user is not None:
        force_authenticate(request, user=user)
    return viewset.as_view({"get": action})(request, **kwargs)


def _scope(viewset: type[Any], user: Any) -> str:
    request = APIRequestFactory().get("/")
    force_authenticate(request, user=user)
    view = viewset()
    view.action_map = {"get": "list"}
    view.request = view.initialize_request(request)
    view.action, view.args, view.kwargs, view.format_kwarg = "list", (), {}, None
    return access_scope(view)


# keys


def test_the_query_string_is_normalised() -> None:
    def key(query: str) -> str:
        return normalized_query(QueryDict(query))

    expected = "a=1&b=2&expand=tags%2Cvenue&status__in=a%2Cb"
    assert key("b=2&a=1&expand=venue,tags&status__in=b,a") == expected
    assert key("expand=tags,venue,&a=1&search=&b=2&status__in=a,b") == expected
    # The order of ?ordering= and ?search= means something: it is kept.
    assert key("ordering=title,starts_at") != key("ordering=starts_at,title")
    assert key("search=b,a") == "search=b%2Ca"


def test_equivalent_urls_share_an_entry(event: Event) -> None:
    first = _get(PublicEvents, "/?expand=venue,tags&page=1")
    assert first["X-Cache"] == "MISS"
    assert _get(PublicEvents, "/?page=1&expand=tags,venue")["X-Cache"] == "HIT"
    assert _get(PublicEvents, "/?expand=tags,venue&search=&page=1")["X-Cache"] == "HIT"
    assert _get(PublicEvents, "/?ordering=title,starts_at")["X-Cache"] == "MISS"
    assert _get(PublicEvents, "/?ordering=starts_at,title")["X-Cache"] == "MISS"


def test_an_entry_key_names_its_resource(event: Event) -> None:
    _get(PublicEvents)
    keys = [key for key in default_cache._cache if ":karni:api:r:" in key]
    assert len(keys) == 1 and ":karni:api:r:testapp.event:" in keys[0]


# who shares an entry


def test_callers_with_the_same_roles_share_a_role_only_entry(event: Event) -> None:
    ann, bob = _user("ann@example.com", "reader"), _user("bob@example.com", "reader")
    assert _get(ReaderEvents, user=ann)["X-Cache"] == "MISS"
    shared = _get(ReaderEvents, user=bob)
    assert shared["X-Cache"] == "HIT" and shared.data["count"] == 1
    assert _scope(ReaderEvents, ann) == _scope(ReaderEvents, bob)
    assert _scope(ReaderEvents, ann).startswith("roles:reader|su:0|staff:0")


def test_other_roles_or_flags_never_share(event: Event) -> None:
    _get(ReaderEvents, user=_user("ann@example.com", "reader"))
    assert _get(ReaderEvents, user=_user("cat@example.com", "reader", "editor"))["X-Cache"] == (
        "MISS"
    )
    assert _get(ReaderEvents, user=_user("dan@example.com", "reader", is_staff=True))[
        "X-Cache"
    ] == ("MISS")


@pytest.mark.parametrize(
    "viewset",
    [OwnedEvents, WhereEvents, FilteredEvents, StarredEvents],
    ids=["owned", "where", "get_queryset", "method-field"],
)
def test_anything_beyond_roles_keys_per_user(event: Event, viewset: type[Any]) -> None:
    ann, bob = _user("ann@example.com", "reader"), _user("bob@example.com", "reader")
    assert _scope(viewset, ann).startswith(f"user:{ann.pk}|")
    assert _get(viewset, user=ann)["X-Cache"] == "MISS"
    assert _get(viewset, user=bob)["X-Cache"] == "MISS"
    assert _get(viewset, user=ann)["X-Cache"] == "HIT"


def test_grants_share_only_when_every_scope_is_all(event: Event, settings: Any) -> None:
    settings.KARNI_ROLES = {
        "viewer": {"grants": {"testapp.event:view": "all"}},
        "author": {"grants": {"testapp.event:view": "own"}},
    }
    sync_roles()
    one, two = _user("one@example.com", "viewer"), _user("two@example.com", "viewer")
    assert _scope(GrantedEvents, one) == _scope(GrantedEvents, two)
    assert _scope(GrantedEvents, one).endswith("|can:testapp.event:view")
    _get(GrantedEvents, user=one)
    assert _get(GrantedEvents, user=two)["X-Cache"] == "HIT"
    ann, bob = _user("ann@example.com", "author"), _user("bob@example.com", "author")
    assert _scope(GrantedEvents, ann).startswith(f"user:{ann.pk}|")
    _get(GrantedEvents, user=ann)
    assert _get(GrantedEvents, user=bob)["X-Cache"] == "MISS"


def test_the_scope_is_overridable_per_viewset(event: Event) -> None:
    class PerUser(ReaderEvents):
        def get_cache_scope(self) -> str:
            return f"user:{self.request.user.pk}"

    ann, bob = _user("ann@example.com", "reader"), _user("bob@example.com", "reader")
    _get(PerUser, user=ann)
    assert _get(PerUser, user=bob)["X-Cache"] == "MISS"


def test_anonymous_callers_share_one_entry(event: Event) -> None:
    assert _get(PublicEvents)["X-Cache"] == "MISS"
    assert _get(PublicEvents)["X-Cache"] == "HIT"
    assert _scope(PublicEvents, None) == "anonymous"


# headers


def test_every_cacheable_response_says_hit_or_miss(event: Event) -> None:
    first, second = _get(PublicEvents), _get(PublicEvents)
    assert (first["X-Cache"], second["X-Cache"]) == ("MISS", "HIT")
    # Deprecated in 0.4.1, removed in 1.0.
    assert (first["X-Karni-Cache"], second["X-Karni-Cache"]) == ("miss", "hit")
    detail = _get(PublicEvents, action="retrieve", pk=str(event.pk))
    assert detail["X-Cache"] == "MISS"


def test_staff_may_bypass_the_cache(event: Event) -> None:
    staff = _user("staff@example.com", is_staff=True)
    bypass = {"X-Bypass-Cache": "1"}
    first = _get(PublicEvents, user=staff, headers=bypass)
    assert first["X-Cache"] == "BYPASS" and "X-Karni-Cache" not in first
    assert _get(PublicEvents, user=staff)["X-Cache"] == "MISS"  # the bypass stored nothing
    assert _get(PublicEvents, user=staff)["X-Cache"] == "HIT"
    assert _get(PublicEvents, user=staff, headers=bypass)["X-Cache"] == "BYPASS"


def test_the_bypass_header_is_ignored_for_everyone_else(event: Event) -> None:
    bypass = {"X-Bypass-Cache": "1"}
    assert _get(PublicEvents, headers=bypass)["X-Cache"] == "MISS"
    assert _get(PublicEvents, headers=bypass)["X-Cache"] == "HIT"
    member = _user("member@example.com", "reader")
    _get(ReaderEvents, user=member, headers=bypass)
    assert _get(ReaderEvents, user=member, headers=bypass)["X-Cache"] == "HIT"


def test_uncached_and_disabled_responses_carry_no_header(event: Event) -> None:
    class Live(PublicEvents):
        cache: ClassVar[Cache | Uncached | None] = Uncached(reason="changes every second")

    assert "X-Cache" not in _get(Live)
    with override_settings(KARNI_API_CACHE=False):
        assert "X-Cache" not in _get(PublicEvents)


# keys of any type


def test_details_key_on_the_canonical_pk_of_either_key_type(event: Event) -> None:
    """Integer keys (KARNI_TEST_PK=bigint) and UUIDs alike: another spelling, the same row."""
    spelled = f"00{event.pk}" if isinstance(event.pk, int) else str(event.pk).upper()

    def detail(pk: str) -> Any:
        return _get(PublicEvents, f"/events/{pk}/", action="retrieve", pk=pk)

    assert detail(spelled)["X-Cache"] == "MISS"
    assert detail(str(event.pk))["X-Cache"] == "MISS"  # another path, another entry
    assert detail(spelled)["X-Cache"] == "HIT"
    event.title = "Renamed"
    event.save()  # replaces the row's token, whichever spelling the entry was stored under
    changed = detail(spelled)
    assert changed["X-Cache"] == "MISS" and changed.data["title"] == "Renamed"
    assert detail(str(event.pk))["X-Cache"] == "MISS"
