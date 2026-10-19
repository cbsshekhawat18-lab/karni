"""``Granted()``: the roles' grants as a viewset's access, row scope included (ADR 0002, P2).

The viewsets live here and are routed through a router factory, so the
project-wide schema snapshot never sees them.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.api import Access, BaseViewSet, Can, Granted, HasRole
from karni.api.access import AnyOf, action_predicate, granted_action, predicate_leaves
from karni.api.routers import KarniRouter
from karni.scoping import scope_exemptions
from tests.testapp.models import Event, Venue

pytestmark = pytest.mark.django_db

ROUTER = "tests.api.test_granted"

ROLES = {
    "staff": {"system": True, "grants": {"*": "all"}},
    "organizer": {
        "grants": {
            "testapp.event:view": "own",
            "testapp.event:change": "own",
            "testapp.event:delete": "own",
            "testapp.event:add": "all",
            "testapp.venue:view": "all",
        }
    },
    "venue_manager": {
        "grants": {
            "testapp.event:view": "related:venue",
            "testapp.event:approve": "related:venue",
            "testapp.venue:view": "all",
        }
    },
    "reader": {"grants": {"testapp.event:view": "all"}},
    "editor": {"grants": {"testapp.event:view": "all", "testapp.event:change": "own"}},
    "auditor": {"grants": {"testapp.venue:view": "all"}},
}


@pytest.fixture(autouse=True)
def _roles() -> Any:
    with override_settings(KARNI_ROLES=ROLES):
        sync_roles()
        yield


# viewsets under test


class GrantedEvents(BaseViewSet):
    """The default declaration: whatever the roles grant for Event."""

    model = Event
    access = Granted()

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        """Declared in ``Event.Karni.actions`` — its own permission."""
        return Response({"id": str(self.get_object().pk)})

    @action(detail=True, methods=["get"])
    def peek(self, request: Request, pk: str | None = None) -> Response:
        """A safe custom action reads: the ``view`` permission."""
        return Response({"id": str(self.get_object().pk)})


class GrantedVenues(BaseViewSet):
    model = Venue
    access = Granted()


class ExemptEvents(BaseViewSet):
    model = Event
    access = Granted()
    scope_exempt = True
    scope_exempt_reason = "every event is visible to anyone allowed to read events"


class MixedEvents(BaseViewSet):
    model = Event
    access = Access(read=Granted() | HasRole("auditor"), write=Granted())


def granted_router() -> KarniRouter:
    router = KarniRouter()
    router.register("granted-events", GrantedEvents, basename="granted-events")
    router.register("granted-venues", GrantedVenues, basename="granted-venues")
    router.register("exempt-events", ExemptEvents, basename="exempt-events")
    router.autodiscover()
    return router


# helpers


def _user(email: str, *roles: str, **attrs: Any) -> Any:
    user = get_user_model().objects.create_user(email=email, password="a-strong-password-123")
    for role in roles:
        assign_role(user, role)
    for name, value in attrs.items():
        setattr(user, name, value)
    return user


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


def _view(action_name: str | None, method: str = "GET", model: Any = Event) -> Any:
    return SimpleNamespace(model=model, action=action_name, request=SimpleNamespace(method=method))


# binding


def test_binding_resolves_the_model_and_the_action() -> None:
    assert granted_action(_view("list")) == "view"
    assert granted_action(_view("retrieve")) == "view"
    assert granted_action(_view("create", "POST")) == "add"
    assert granted_action(_view("partial_update", "PATCH")) == "change"
    assert granted_action(_view("destroy", "DELETE")) == "delete"
    assert granted_action(_view("approve", "POST")) == "approve"  # Event.Karni.actions
    assert granted_action(_view("peek")) == "view"  # safe custom action reads
    assert granted_action(_view(None, "PATCH")) == "change"
    view = GrantedEvents()
    declaration = view.get_access()
    assert isinstance(declaration, Access)
    view.action, view.request = "destroy", SimpleNamespace(method="DELETE")
    assert action_predicate(view, declaration) == Can("testapp.event:delete")
    view.action, view.request = "create", SimpleNamespace(method="POST")
    assert action_predicate(view, declaration) == Can("testapp.event:add")
    assert Granted().bind(view, "view") == Can("testapp.event:view")
    assert repr(Granted()) == "Granted()" and Granted().describe() == {"granted": True}


def test_unbound_granted_is_an_error_not_a_silent_deny() -> None:
    request = SimpleNamespace(user=AnonymousUser(), method="GET")
    with pytest.raises(ImproperlyConfigured, match="E211"):
        Granted().rows(request)
    with pytest.raises(ImproperlyConfigured, match="E211"):
        Granted().allows(request)


def test_granted_needs_the_viewsets_model() -> None:
    with pytest.raises(ImproperlyConfigured, match="E211"):

        class _NoModel(BaseViewSet):
            access = Granted()

            def get_queryset(self) -> Any:
                return Event.objects.all()


def test_an_unsafe_action_the_model_never_declared_is_e211() -> None:
    with pytest.raises(ImproperlyConfigured, match="E211.*export"):

        class _Undeclared(BaseViewSet):
            model = Event
            access = Granted()

            @action(detail=True, methods=["post"])
            def export(self, request: Request, pk: str | None = None) -> Response:
                return Response({})

    class _SafeIsFine(BaseViewSet):  # a GET action reads
        model = Event
        access = Granted()

        @action(detail=True, methods=["get"])
        def summary(self, request: Request, pk: str | None = None) -> Response:
            return Response({})

    class _OwnPredicate(BaseViewSet):  # its own access= needs no permission
        model = Event
        access = Granted()

        @action(detail=True, methods=["post"], access=HasRole("staff"))
        def export(self, request: Request, pk: str | None = None) -> Response:
            return Response({})

    for viewset in (_SafeIsFine, _OwnPredicate, GrantedEvents):
        # The bare shorthand becomes a full declaration at class definition.
        assert isinstance(viewset.access, Access)
        assert viewset.access.read == viewset.access.write == viewset.access.create == Granted()


def test_combines_with_other_predicates() -> None:
    view = GrantedEvents()
    view.action, view.request = "list", SimpleNamespace(method="GET")
    bound = MixedEvents.access.read.bind(view)
    assert isinstance(bound, AnyOf)
    assert bound.parts == (Can("testapp.event:view"), HasRole("auditor"))
    assert MixedEvents.access.read.bind(SimpleNamespace(model=None)) is MixedEvents.access.read
    assert [type(p).__name__ for p in predicate_leaves(MixedEvents.access.read)] == [
        "HasRole",
        "Granted",
    ]


# gate and rows


def test_the_gate_and_the_rows_follow_the_grants() -> None:
    alice = _user("alice@example.com", "organizer")
    bob = _user("bob@example.com", "organizer")
    reader = _user("reader@example.com", "reader")
    nobody = _user("nobody@example.com")
    mine = _event("Mine", organizer=alice)
    theirs = _event("Theirs", organizer=bob)
    assert _ids(_list(GrantedEvents, alice)) == {str(mine.pk)}
    assert _ids(_list(GrantedEvents, reader)) == {str(mine.pk), str(theirs.pk)}
    denied = _list(GrantedEvents, nobody)
    assert denied.status_code == 403
    assert "Can('testapp.event:view')" in str(denied.data["detail"])
    assert _list(GrantedEvents).status_code == 401


def test_out_of_scope_is_404_naming_the_bound_scope() -> None:
    alice = _user("alice@example.com", "organizer")
    theirs = _event("Theirs", organizer=_user("bob@example.com", "organizer"))
    response = _call(GrantedEvents, {"get": "retrieve"}, user=alice, pk=str(theirs.pk))
    assert response.status_code == 404
    detail = str(response.data["detail"])
    assert "GrantedEvents.access read=Granted() (= Can('testapp.event:view'))" in detail
    peek = _call(GrantedEvents, {"get": "peek"}, user=alice, pk=str(theirs.pk))
    assert peek.status_code == 404


def test_related_scope_follows_the_users_side_of_the_path() -> None:
    here = Venue.objects.create(name="Here", city="Berlin")
    there = Venue.objects.create(name="There", city="Rome")
    manager = _user("manager@example.com", "venue_manager", venue=here)
    at_here = _event("At here", venue=here)
    at_there = _event("At there", venue=there)
    assert _ids(_list(GrantedEvents, manager)) == {str(at_here.pk)}
    ok = _call(GrantedEvents, {"post": "approve"}, user=manager, method="post", pk=str(at_here.pk))
    assert ok.status_code == 200, ok.data
    hidden = _call(
        GrantedEvents, {"post": "approve"}, user=manager, method="post", pk=str(at_there.pk)
    )
    assert hidden.status_code == 404
    without = _user("lost@example.com", "venue_manager")  # no venue: fails closed
    assert _ids(_list(GrantedEvents, without)) == set()


def test_writes_need_the_change_grant_on_a_readable_row() -> None:
    editor = _user("editor@example.com", "editor")  # view all, change own
    reader = _user("reader@example.com", "reader")  # view all, change nothing
    mine = _event("Mine", organizer=editor)
    theirs = _event("Theirs", organizer=reader)
    forbidden = _call(
        GrantedEvents,
        {"patch": "partial_update"},
        user=editor,
        method="patch",
        data={"title": "x"},
        pk=str(theirs.pk),
    )
    assert forbidden.status_code == 403
    assert "Can('testapp.event:change')" in str(forbidden.data["detail"])
    allowed = _call(
        GrantedEvents,
        {"patch": "partial_update"},
        user=editor,
        method="patch",
        data={"title": "Renamed"},
        pk=str(mine.pk),
    )
    assert allowed.status_code == 200, allowed.data
    gate = _call(
        GrantedEvents,
        {"patch": "partial_update"},
        user=reader,
        method="patch",
        data={"title": "x"},
        pk=str(mine.pk),
    )
    assert gate.status_code == 403
    delete = _call(
        GrantedEvents, {"delete": "destroy"}, user=reader, method="delete", pk=str(mine.pk)
    )
    assert delete.status_code == 403
    assert Event.objects.filter(pk=mine.pk).exists()


def test_create_needs_add_and_stamps_the_owner_field() -> None:
    alice = _user("alice@example.com", "organizer")
    bob = _user("bob@example.com", "organizer")
    reader = _user("reader@example.com", "reader")
    body = {"title": "New", "starts_at": "2030-01-01T00:00:00Z", "organizer": str(bob.pk)}
    assert (
        _call(GrantedEvents, {"post": "create"}, user=reader, method="post", data=body).status_code
        == 403
    )
    created = _call(GrantedEvents, {"post": "create"}, user=alice, method="post", data=body)
    assert created.status_code == 201, created.data
    assert Event.objects.get(pk=created.data["id"]).organizer == alice  # Karni.owner_field
    assert GrantedEvents().get_owner_fields() == ("organizer",)
    assert GrantedEvents().get_serializer_class()().fields["organizer"].read_only is True


# scope_exempt


def test_scope_exempt_keeps_the_gate_and_drops_the_rows() -> None:
    alice = _user("alice@example.com", "organizer")
    nobody = _user("nobody@example.com")
    mine = _event("Mine", organizer=alice)
    theirs = _event("Theirs", organizer=_user("bob@example.com", "organizer"))
    assert _ids(_list(ExemptEvents, alice)) == {str(mine.pk), str(theirs.pk)}
    assert (
        _call(ExemptEvents, {"get": "retrieve"}, user=alice, pk=str(theirs.pk)).status_code == 200
    )
    assert _list(ExemptEvents, nobody).status_code == 403
    with pytest.raises(ImproperlyConfigured, match="E210"):

        class _NoReason(BaseViewSet):
            model = Event
            access = Granted()
            scope_exempt = True


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.granted_router")
def test_scope_exemptions_are_listed() -> None:
    found = {(item.kind, item.name): item.reason for item in scope_exemptions()}
    assert found[("viewset", "ExemptEvents")].startswith("every event is visible")
    assert ("viewset", "GrantedEvents") not in found


# performance: scope composes with the optimiser


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.granted_router")
def test_related_scope_adds_no_query_per_row(django_assert_num_queries: Any) -> None:
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    here = Venue.objects.create(name="Here", city="Berlin")
    manager = _user("manager@example.com", "venue_manager", venue=here)
    _list(GrantedEvents, manager)  # the grants are looked up once per user instance

    def count(rows: int) -> int:
        Event.objects.all().delete()
        for index in range(rows):
            _event(f"Event {index}", venue=here)
        with CaptureQueriesContext(connection) as captured:
            response = _list(GrantedEvents, manager, expand="venue")
            assert response.data["count"] == rows
            assert all(row["venue"]["name"] == "Here" for row in response.data["results"])
        return len(captured)

    assert count(2) == count(12)


# the schema


@override_settings(KARNI_API_ROUTER=f"{ROUTER}.granted_router")
def test_the_schema_publishes_the_bound_permissions() -> None:
    paths = SchemaGenerator(patterns=granted_router().urls).get_schema(request=None, public=True)[
        "paths"
    ]
    assert paths["/granted-events/"]["get"]["x-karni-access"] == {"can": ["testapp.event:view"]}
    assert paths["/granted-events/"]["post"]["x-karni-access"] == {"can": ["testapp.event:add"]}
    assert paths["/granted-events/{id}/"]["patch"]["x-karni-access"] == {
        "can": ["testapp.event:change"]
    }
    assert paths["/granted-events/{id}/"]["delete"]["x-karni-access"] == {
        "can": ["testapp.event:delete"]
    }
    assert paths["/granted-events/{id}/approve/"]["post"]["x-karni-access"] == {
        "can": ["testapp.event:approve"]
    }
    assert paths["/granted-events/{id}/peek/"]["get"]["x-karni-access"] == {
        "can": ["testapp.event:view"]
    }
