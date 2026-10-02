"""Access declarations (ADR 0001 Decision 2): predicates, gates, row scope, relations.

Viewsets here live in this test module, so the auto-router never sees them;
tests that need a *routed* target (relation PK validation, ``?expand=``)
point ``KARNI_API_ROUTER`` at a factory below that registers them first.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q, QuerySet
from django.test import override_settings
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from karni.accounts.permissions import assign_role
from karni.api import (
    Access,
    Authenticated,
    BaseViewSet,
    Can,
    HasRole,
    Owned,
    Public,
    Unscoped,
    Where,
)
from karni.api.access import AnyOf, apply_rows, request_roles
from karni.api.routers import KarniRouter
from karni.api.serializers import build_serializer
from tests.testapp.models import Event, Tag, Venue
from tests.testapp.viewsets import EventViewSet

pytestmark = pytest.mark.django_db

ROUTER = "tests.api.test_access"


# --- viewsets under test --------------------------------------------------------------


class OwnedEvents(BaseViewSet):
    """The ADR's worked example."""

    model = Event
    access = Access(
        read=Owned("organizer") | HasRole("staff"),
        write=Owned("organizer"),
        create=Authenticated(),
    )


class ActionEvents(OwnedEvents):
    @action(detail=True, methods=["get"])
    def peek(self, request: Request, pk: str | None = None) -> Response:
        return Response({"id": str(self.get_object().pk)})

    @action(detail=True, methods=["post"])
    def touch(self, request: Request, pk: str | None = None) -> Response:
        return Response({"id": str(self.get_object().pk)})

    @action(detail=True, methods=["post"], access=HasRole("moderator"))
    def moderate(self, request: Request, pk: str | None = None) -> Response:
        return Response({"id": str(self.get_object().pk)})


class _PublicOnlyMixin:
    def get_queryset(self) -> QuerySet[Any]:
        return Event.objects.filter(is_public=True)


class OverrideWithoutSuper(OwnedEvents):
    def get_queryset(self) -> QuerySet[Any]:
        return Event.objects.filter(is_public=True)


class OverrideWithSuper(OwnedEvents):
    def get_queryset(self) -> QuerySet[Any]:
        return super().get_queryset().filter(is_public=True)


class MixinOverride(_PublicOnlyMixin, OwnedEvents):
    pass


class NoAccessEvents(BaseViewSet):
    model = Event


class NoAccessTags(BaseViewSet):
    model = Tag


class BerlinVenues(BaseViewSet):
    model = Venue
    access = Access(read=Where(lambda request: Q(city="Berlin")), write=Authenticated())


class TaggerTags(BaseViewSet):
    model = Tag
    access = Access(read=HasRole("tagger"), write=HasRole("tagger"))


class VenueCatalogue(BaseViewSet):
    model = Venue
    access = Unscoped(reason="legacy public catalogue")
    permission_classes = [IsAuthenticatedOrReadOnly]


class VenuesWithEvents(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=Authenticated())
    expandable_fields = {"events": "events"}


def scoped_router() -> KarniRouter:
    """Venue, Tag and Event targets with narrowing read scopes, registered first."""
    router = KarniRouter()
    router.register("berlin-venues", BerlinVenues, basename="berlin-venues")
    router.register("tagger-tags", TaggerTags, basename="tagger-tags")
    router.register("owned-events", OwnedEvents, basename="owned-events")
    router.autodiscover()
    return router


def deny_router() -> KarniRouter:
    """Tag served by a viewset without an access declaration."""
    router = KarniRouter()
    router.register("no-access-tags", NoAccessTags, basename="no-access-tags")
    router.autodiscover()
    return router


# --- fixtures & helpers ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_throttle_state() -> Any:
    yield
    cache.clear()


def _user(email: str, *roles: str) -> Any:
    user = get_user_model().objects.create_user(email=email, password="a-strong-password-123")
    for role in roles:
        assign_role(user, role)
    return user


@pytest.fixture
def alice() -> Any:
    return _user("alice@example.com")


@pytest.fixture
def bob() -> Any:
    return _user("bob@example.com")


@pytest.fixture
def staff() -> Any:
    return _user("staff@example.com", "staff")


def _event(title: str = "Event", **kwargs: Any) -> Event:
    kwargs.setdefault("starts_at", timezone.now())
    return Event.objects.create(title=title, **kwargs)


def _call(
    viewset: type[Any],
    actions: dict[str, str],
    *,
    user: Any = None,
    method: str = "get",
    data: Any = None,
    query: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    factory = APIRequestFactory()
    if method == "get":
        request = factory.get("/", query or {})
    else:
        request = getattr(factory, method)("/", data or {}, format="json")
    if user is not None:
        force_authenticate(request, user=user)
    return viewset.as_view(actions)(request, **kwargs)


def _list(viewset: type[Any], user: Any = None, **query: Any) -> Any:
    return _call(viewset, {"get": "list"}, user=user, query=query)


def _ids(response: Any) -> set[str]:
    assert response.status_code == 200, response.data
    return {str(row["id"]) for row in response.data["results"]}


def _req(user: Any = None) -> Any:
    return SimpleNamespace(user=user or AnonymousUser(), method="GET")


# --- predicates: request level and row level ------------------------------------------


def test_public_admits_everyone_and_every_row() -> None:
    assert Public().allows(_req()) is True
    assert Public().rows(_req()) is True


def test_authenticated_requires_a_user(alice: Any) -> None:
    assert Authenticated().allows(_req()) is False
    assert Authenticated().rows(_req()) is False
    assert Authenticated().allows(_req(alice)) is True
    assert Authenticated().rows(_req(alice)) is True


def test_has_role_matches_any_named_role(alice: Any, staff: Any) -> None:
    assert HasRole("staff", "editor").allows(_req(staff)) is True
    assert HasRole("staff").rows(_req(staff)) is True
    assert HasRole("staff").allows(_req(alice)) is False
    assert HasRole("staff").rows(_req()) is False


def test_role_lookups_cost_one_query_per_request(
    staff: Any, django_assert_num_queries: Any
) -> None:
    request = _req(staff)
    with django_assert_num_queries(1):
        assert HasRole("staff").allows(request)
        assert not HasRole("editor").allows(request)
        assert (HasRole("a") | HasRole("staff")).rows(request) is True
    assert request_roles(request) == frozenset({"staff"})


def test_owned_compiles_to_a_q_on_the_owner_path(alice: Any) -> None:
    assert Owned("organizer").allows(_req()) is False
    assert Owned("organizer").rows(_req()) is False
    assert Owned("organizer").allows(_req(alice)) is True
    assert Owned("organizer").rows(_req(alice)) == Q(organizer=alice)


def test_owned_without_a_field_is_a_class_definition_error_naming_the_fix() -> None:
    with pytest.raises(ImproperlyConfigured, match=r'Owned\("organizer"\)') as excinfo:

        class _Broken(BaseViewSet):
            model = Event
            access = Access(read=Owned(), write=Owned())

    assert "created_by" in str(excinfo.value)


def test_owned_path_must_reach_the_user_model() -> None:
    with pytest.raises(ImproperlyConfigured, match="_WrongPath.*ends at Venue"):

        class _WrongPath(BaseViewSet):
            model = Event
            access = Access(read=Owned("venue"), write=Authenticated())

    with pytest.raises(ImproperlyConfigured, match="has no field 'nope'"):

        class _Missing(BaseViewSet):
            model = Event
            access = Access(read=Owned("nope"), write=Authenticated())


def test_owned_pk_on_the_user_model_is_valid(alice: Any, bob: Any) -> None:
    class _Self(BaseViewSet):
        model = get_user_model()
        access = Access(read=Owned("pk"), write=Owned("pk"))

    assert _ids(_list(_Self, alice)) == {str(alice.pk)}


def test_owned_bypass_is_an_or(alice: Any, bob: Any, staff: Any) -> None:
    declared = Owned("organizer", bypass=HasRole("staff"))
    assert declared.rows(_req(staff)) is True
    assert declared.rows(_req(alice)) == Q(organizer=alice)
    assert declared.describe() == {"any": [{"owned": "organizer"}, {"role": ["staff"]}]}


def test_where_returns_a_q_or_a_bool(alice: Any) -> None:
    rows = Where(lambda request: Q(is_public=True))
    assert rows.allows(_req()) is True
    assert rows.rows(_req()) == Q(is_public=True)
    corp = Where(lambda request: request.user.is_authenticated)
    assert corp.allows(_req()) is False
    assert corp.rows(_req(alice)) is True
    with pytest.raises(ImproperlyConfigured, match="must return a Q or a bool"):
        Where(lambda request: "nope").rows(_req())


def test_or_and_and_compose(alice: Any, staff: Any) -> None:
    either = Owned("organizer") | HasRole("staff") | Public()
    assert isinstance(either, AnyOf) and len(either.parts) == 3
    assert either.rows(_req()) is True
    both = Owned("organizer") & Where(lambda request: Q(is_public=True))
    assert both.allows(_req()) is False
    assert both.rows(_req(alice)) == Q(organizer=alice) & Q(is_public=True)
    assert (HasRole("staff") & Authenticated()).rows(_req(alice)) is False
    assert repr(Owned("a") | HasRole("b") & Public()) == "Owned('a') | HasRole('b') & Public()"


def test_python_or_and_on_predicates_is_refused() -> None:
    with pytest.raises(TypeError, match=r"\| and &"):
        _ = Owned("organizer") or HasRole("staff")


def test_declaration_errors_name_the_fix() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"write Public\(\)"):
        Access(read=Public, write=Authenticated())  # type: ignore[arg-type]
    with pytest.raises(ImproperlyConfigured, match="Access"):

        class _Bare(BaseViewSet):
            model = Event
            access = Public()  # type: ignore[assignment]

    with pytest.raises(ImproperlyConfigured, match="reason"):
        Unscoped(reason="  ")
    with pytest.raises(ImproperlyConfigured, match="HasRole"):
        HasRole()


def test_can_is_reserved() -> None:
    with pytest.raises(ImproperlyConfigured, match="reserved"):
        Can("events:update")


def test_to_many_owner_paths_are_distinct(alice: Any) -> None:
    class _MyVenues(BaseViewSet):
        model = Venue
        access = Access(read=Owned("events__organizer"), write=Owned("events__organizer"))

    venue = Venue.objects.create(name="Arena", city="Berlin")
    Venue.objects.create(name="Elsewhere", city="Rome")
    _event("One", organizer=alice, venue=venue)
    _event("Two", organizer=alice, venue=venue)
    response = _list(_MyVenues, alice)
    assert response.data["count"] == 1
    assert _ids(response) == {str(venue.pk)}


def test_traversal_paths_follow_foreign_keys(alice: Any, bob: Any) -> None:
    class _ByVenueCreator(BaseViewSet):
        model = Event
        access = Access(read=Owned("venue__created_by"), write=Authenticated())

    mine = Venue.objects.create(name="Mine", city="Berlin", created_by=alice)
    theirs = Venue.objects.create(name="Theirs", city="Berlin", created_by=bob)
    kept = _event("At mine", venue=mine)
    _event("At theirs", venue=theirs)
    assert _ids(_list(_ByVenueCreator, alice)) == {str(kept.pk)}


# --- per-action gates, 404 vs 403 -------------------------------------------------------


def test_list_is_row_scoped_and_roles_bypass(alice: Any, bob: Any, staff: Any) -> None:
    own = _event("Mine", organizer=alice)
    other = _event("Theirs", organizer=bob)
    assert _ids(_list(OwnedEvents, alice)) == {str(own.pk)}
    assert _ids(_list(OwnedEvents, staff)) == {str(own.pk), str(other.pk)}
    assert _list(OwnedEvents).status_code == 401


def test_out_of_scope_retrieve_is_404_naming_the_scope(alice: Any, bob: Any) -> None:
    other = _event("Theirs", organizer=bob)
    response = _call(OwnedEvents, {"get": "retrieve"}, user=alice, pk=str(other.pk))
    assert response.status_code == 404
    assert "OwnedEvents.access read=Owned('organizer') | HasRole('staff')" in str(
        response.data["detail"]
    )


def test_readable_but_not_writable_is_403(alice: Any, staff: Any) -> None:
    event = _event("Mine", organizer=alice)
    patch = _call(
        OwnedEvents,
        {"patch": "partial_update"},
        user=staff,
        method="patch",
        data={"title": "Hijacked"},
        pk=str(event.pk),
    )
    assert patch.status_code == 403
    assert "Owned('organizer')" in str(patch.data["detail"])
    delete = _call(
        OwnedEvents, {"delete": "destroy"}, user=staff, method="delete", pk=str(event.pk)
    )
    assert delete.status_code == 403
    event.refresh_from_db()
    assert event.title == "Mine"


def test_unreadable_write_is_404_and_own_write_succeeds(alice: Any, bob: Any) -> None:
    other = _event("Theirs", organizer=bob)
    mine = _event("Mine", organizer=alice)
    denied = _call(
        OwnedEvents,
        {"patch": "partial_update"},
        user=alice,
        method="patch",
        data={"title": "x"},
        pk=str(other.pk),
    )
    assert denied.status_code == 404
    allowed = _call(
        OwnedEvents,
        {"patch": "partial_update"},
        user=alice,
        method="patch",
        data={"title": "Renamed"},
        pk=str(mine.pk),
    )
    assert allowed.status_code == 200, allowed.data


def test_create_gate_and_owner_stamping(alice: Any, bob: Any) -> None:
    anonymous = _call(
        OwnedEvents,
        {"post": "create"},
        method="post",
        data={"title": "x", "starts_at": "2030-01-01T00:00:00Z"},
    )
    assert anonymous.status_code == 401
    response = _call(
        OwnedEvents,
        {"post": "create"},
        user=alice,
        method="post",
        data={"title": "Mine", "starts_at": "2030-01-01T00:00:00Z", "organizer": str(bob.pk)},
    )
    assert response.status_code == 201, response.data
    assert Event.objects.get(pk=response.data["id"]).organizer == alice


def test_owner_field_is_read_only_in_the_generated_serializer() -> None:
    assert OwnedEvents().get_owner_fields() == ("organizer",)
    fields = OwnedEvents().get_serializer_class()().fields
    assert fields["organizer"].read_only is True
    assert EventViewSet().get_serializer_class()().fields["organizer"].read_only is False


def test_custom_actions_inherit_read_or_write(alice: Any, staff: Any) -> None:
    event = _event("Mine", organizer=alice)
    peek = _call(ActionEvents, {"get": "peek"}, user=staff, pk=str(event.pk))
    assert peek.status_code == 200  # safe → read (staff may read)
    touch = _call(ActionEvents, {"post": "touch"}, user=staff, method="post", pk=str(event.pk))
    assert touch.status_code == 403  # unsafe → write (only the organizer)
    own = _call(ActionEvents, {"post": "touch"}, user=alice, method="post", pk=str(event.pk))
    assert own.status_code == 200


def test_action_access_override(alice: Any, staff: Any) -> None:
    moderator = _user("mod@example.com", "moderator", "staff")
    event = _event("Mine", organizer=alice)
    owner = _call(ActionEvents, {"post": "moderate"}, user=alice, method="post", pk=str(event.pk))
    assert owner.status_code == 403  # the override replaces write for this action
    ok = _call(ActionEvents, {"post": "moderate"}, user=moderator, method="post", pk=str(event.pk))
    assert ok.status_code == 200
    # The lookup still runs through read: a moderator without read reach gets 404.
    lone = _user("lone@example.com", "moderator")
    missing = _call(ActionEvents, {"post": "moderate"}, user=lone, method="post", pk=str(event.pk))
    assert missing.status_code == 404


def test_get_access_hatch_computes_a_declaration(alice: Any, bob: Any) -> None:
    class _Dynamic(BaseViewSet):
        model = Event

        def get_access(self) -> Access:
            return Access(read=Owned("organizer"), write=Owned("organizer"))

    own = _event("Mine", organizer=alice)
    _event("Theirs", organizer=bob)
    assert _ids(_list(_Dynamic, alice)) == {str(own.pk)}


# --- deny-all without a declaration ------------------------------------------------------


def test_missing_access_denies_everything_and_names_the_fix(alice: Any) -> None:
    _event("Hidden")
    for user in (None, alice):
        response = _list(NoAccessEvents, user)
        assert response.status_code == 403
        assert "declares no `access`" in str(response.data["detail"])
        assert "Access(read=" in str(response.data["detail"])
    created = _call(
        NoAccessEvents,
        {"post": "create"},
        user=alice,
        method="post",
        data={"title": "x", "starts_at": "2030-01-01T00:00:00Z"},
    )
    assert created.status_code == 403
    assert Event.objects.count() == 1


def test_missing_access_row_scope_is_empty(alice: Any) -> None:
    _event("Hidden")
    view = NoAccessEvents()
    view.request = Request(APIRequestFactory().get("/"))
    view.format_kwarg = None
    assert view.get_queryset().count() == 0


# --- get_queryset overrides stay scoped (Q2.7) --------------------------------------------


@pytest.mark.parametrize("viewset", [OverrideWithoutSuper, OverrideWithSuper, MixinOverride])
def test_overridden_get_queryset_is_still_read_scoped(
    viewset: type[Any], alice: Any, bob: Any
) -> None:
    mine = _event("Mine", organizer=alice, is_public=True)
    _event("Mine, private", organizer=alice, is_public=False)
    other = _event("Theirs", organizer=bob, is_public=True)
    assert _ids(_list(viewset, alice)) == {str(mine.pk)}
    detail = _call(viewset, {"get": "retrieve"}, user=alice, pk=str(other.pk))
    assert detail.status_code == 404


def test_super_chain_scopes_exactly_once(alice: Any) -> None:
    view = OverrideWithSuper()
    view.request = Request(APIRequestFactory().get("/"))
    force_authenticate(view.request, user=alice)
    view.request.user = alice
    view.format_kwarg = None
    sql = str(view.get_queryset().query)
    assert sql.count('"organizer_id" =') == 1


# --- Unscoped and Public --------------------------------------------------------------------


def test_unscoped_hands_the_gate_to_drf(alice: Any) -> None:
    venue = Venue.objects.create(name="Arena", city="Rome")
    assert _ids(_list(VenueCatalogue)) == {str(venue.pk)}  # IsAuthenticatedOrReadOnly
    anonymous = _call(
        VenueCatalogue, {"post": "create"}, method="post", data={"name": "x", "city": "y"}
    )
    assert anonymous.status_code == 401

    class _DefaultGate(BaseViewSet):
        model = Venue
        access = Unscoped(reason="internal tool")

    assert _list(_DefaultGate).status_code == 401  # DEFAULT_PERMISSION_CLASSES
    assert _ids(_list(_DefaultGate, alice)) == {str(venue.pk)}


def test_public_read_is_explicit(alice: Any) -> None:
    _event("Open")
    assert _list(EventViewSet).status_code == 200
    assert _list(OwnedEvents).status_code == 401


# --- model-level scopes cannot be lifted ------------------------------------------------------


def _soft_delete(event: Event) -> None:
    Event.objects.filter(pk=event.pk).update(deleted_at=timezone.now())


def test_no_predicate_lifts_soft_delete(staff: Any, alice: Any) -> None:
    gone = _event("Gone", organizer=alice)
    kept = _event("Kept", organizer=alice)
    _soft_delete(gone)

    class _TriesToLift(BaseViewSet):
        model = Event
        access = Access(
            read=Public() | Where(lambda request: Q(deleted_at__isnull=False)),
            write=Authenticated(),
        )

    class _OnlyDeleted(BaseViewSet):
        model = Event
        access = Access(read=Where(lambda request: Q(deleted_at__isnull=False)), write=Public())

    assert _ids(_list(EventViewSet)) == {str(kept.pk)}
    assert _ids(_list(OwnedEvents, staff)) == {str(kept.pk)}
    assert _ids(_list(_TriesToLift)) == {str(kept.pk)}
    assert _ids(_list(_OnlyDeleted)) == set()
    assert _ids(_list(VenueCatalogue)) == set()
    detail = _call(OwnedEvents, {"get": "retrieve"}, user=staff, pk=str(gone.pk))
    assert detail.status_code == 404


def test_apply_rows_only_narrows() -> None:
    _event("Kept")
    base = Event.objects.all()
    assert apply_rows(base, True) is base
    assert apply_rows(base, False).count() == 0
    assert apply_rows(base, Q(title="Kept")).count() == 1


# --- relation PK validation respects the target's read scope (Q2.5) ---------------------------


def _create_event(user: Any, **fields: Any) -> Any:
    data = {"title": "New", "starts_at": "2030-01-01T00:00:00Z", **fields}
    return _call(EventViewSet, {"post": "create"}, user=user, method="post", data=data)


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.scoped_router")
def test_relation_pk_outside_the_target_scope_is_invalid(alice: Any) -> None:
    berlin = Venue.objects.create(name="Arena", city="Berlin")
    rome = Venue.objects.create(name="Colosseo", city="Rome")
    assert _create_event(alice, venue=str(berlin.pk)).status_code == 201
    hidden = _create_event(alice, venue=str(rome.pk))
    assert hidden.status_code == 400
    missing = _create_event(alice, venue="00000000-0000-0000-0000-000000000000")
    # Same error for "exists but unreadable" and "does not exist": no oracle.
    assert str(hidden.data["venue"][0]).replace(str(rome.pk), "<pk>") == str(
        missing.data["venue"][0]
    ).replace("00000000-0000-0000-0000-000000000000", "<pk>")


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.scoped_router")
def test_to_many_relation_pks_respect_the_target_scope(alice: Any) -> None:
    tagger = _user("tagger@example.com", "tagger")
    tag = Tag.objects.create(name="music")
    assert _create_event(alice, tags=[str(tag.pk)]).status_code == 400
    assert _create_event(tagger, tags=[str(tag.pk)]).status_code == 201


def test_unrouted_target_uses_the_default_manager_only(alice: Any) -> None:
    # Tag has no routed viewset by default (TagViewSet.auto_register = False):
    # no row policy, but model scopes (soft delete) still hold.
    tag = Tag.objects.create(name="music")
    gone = Tag.objects.create(name="gone")
    Tag.objects.filter(pk=gone.pk).update(deleted_at=timezone.now())
    assert _create_event(alice, tags=[str(tag.pk)]).status_code == 201
    assert _create_event(alice, tags=[str(gone.pk)]).status_code == 400


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.deny_router")
def test_target_without_access_accepts_no_pk(alice: Any) -> None:
    tag = Tag.objects.create(name="music")
    assert _create_event(alice, tags=[str(tag.pk)]).status_code == 400


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.scoped_router")
def test_serializer_without_a_request_is_not_narrowed() -> None:
    rome = Venue.objects.create(name="Colosseo", city="Rome")
    serializer = build_serializer(Event)(
        data={"title": "x", "starts_at": "2030-01-01T00:00:00Z", "venue": str(rome.pk)}
    )
    assert serializer.is_valid(), serializer.errors


# --- ?expand= only embeds readable rows (Q2.5) ---------------------------------------------------


def test_expanding_users_needs_their_read_scope(alice: Any) -> None:
    _event("Mine", organizer=alice)
    anonymous = _list(EventViewSet, expand="organizer")
    assert anonymous.data["results"][0]["organizer"] is None
    authed = _list(EventViewSet, alice, expand="organizer")
    assert authed.data["results"][0]["organizer"]["email"] == "alice@example.com"


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.scoped_router")
def test_to_one_expansion_into_a_scoped_target(django_assert_num_queries: Any) -> None:
    berlin = Venue.objects.create(name="Arena", city="Berlin")
    rome = Venue.objects.create(name="Colosseo", city="Rome")
    _event("In Berlin", venue=berlin)
    _event("In Rome", venue=rome)
    _event("Also Berlin", venue=berlin)
    # count, events, one scoped venue prefetch — independent of the row count.
    # (tags is expanded too because unexpanded M2Ms are still N+1, ADR fact F7;
    # its scope is empty for anonymous callers, so its prefetch runs no query.)
    with django_assert_num_queries(3):
        response = _list(EventViewSet, expand="venue,tags")
        rows = {row["title"]: row["venue"] for row in response.data["results"]}
    assert rows["In Berlin"]["name"] == "Arena"
    assert rows["Also Berlin"]["name"] == "Arena"
    assert rows["In Rome"] is None


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.scoped_router")
def test_to_many_expansion_into_a_scoped_target(alice: Any) -> None:
    tagger = _user("tagger@example.com", "tagger")
    event = _event("Tagged")
    event.tags.add(Tag.objects.create(name="music"))
    assert _list(EventViewSet, alice, expand="tags").data["results"][0]["tags"] == []
    tags = _list(EventViewSet, tagger, expand="tags").data["results"][0]["tags"]
    assert [tag["name"] for tag in tags] == ["music"]


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.scoped_router")
def test_reverse_expansion_uses_the_target_scope(alice: Any, bob: Any) -> None:
    venue = Venue.objects.create(name="Arena", city="Berlin")
    _event("Mine", organizer=alice, venue=venue)
    _event("Theirs", organizer=bob, venue=venue)
    row = _list(VenuesWithEvents, alice, expand="events").data["results"][0]
    assert [event["title"] for event in row["events"]] == ["Mine"]


# --- x-karni-access in the schema ----------------------------------------------------------------


def _schema(router: KarniRouter) -> dict[str, Any]:
    return SchemaGenerator(patterns=router.urls).get_schema(request=None, public=True)


def test_x_karni_access_on_the_testapp_schema() -> None:
    paths = SchemaGenerator().get_schema(request=None, public=True)["paths"]
    assert paths["/api/events/"]["get"]["x-karni-access"] == {"public": True}
    assert {} in paths["/api/events/"]["get"]["security"]
    assert paths["/api/events/"]["post"]["x-karni-access"] == {"authenticated": True}
    assert {} not in paths["/api/events/"]["post"]["security"]
    assert paths["/api/users/{id}/"]["patch"]["x-karni-access"] == {"role": ["staff"]}


def test_x_karni_access_per_operation() -> None:
    router = KarniRouter()
    router.register("owned", ActionEvents, basename="owned")
    router.register("catalogue", VenueCatalogue, basename="catalogue")
    router.register("denied", NoAccessTags, basename="denied")
    paths = _schema(router)["paths"]
    assert paths["/owned/"]["get"]["x-karni-access"] == {
        "any": [{"owned": "organizer"}, {"role": ["staff"]}]
    }
    assert paths["/owned/"]["post"]["x-karni-access"] == {"authenticated": True}
    assert paths["/owned/{id}/"]["delete"]["x-karni-access"] == {"owned": "organizer"}
    assert paths["/owned/{id}/peek/"]["get"]["x-karni-access"]["any"][0] == {"owned": "organizer"}
    assert paths["/owned/{id}/touch/"]["post"]["x-karni-access"] == {"owned": "organizer"}
    assert paths["/owned/{id}/moderate/"]["post"]["x-karni-access"] == {"role": ["moderator"]}
    assert paths["/catalogue/"]["get"]["x-karni-access"] == {"unscoped": "legacy public catalogue"}
    assert paths["/denied/"]["get"]["x-karni-access"] == {"deny": "no access declared"}
