"""Viewsets and the router ``tests/why`` explains: one per kind of access decision.

Routed through ``KARNI_API_ROUTER = "tests.why.routes.router"`` so the
project-wide schema snapshot never sees them.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from karni.api import Access, Authenticated, BaseViewSet, Granted, HasRole, Owned, Unscoped, Where
from karni.api.routers import KarniRouter
from tests.testapp.models import Customer, Event

ROUTER = "tests.why.routes.router"

PUBLISHED = Where(lambda request: Q(status=Event.Status.PUBLISHED))

#: The roles every why test runs with (tests.why.conftest syncs them).
ROLES: dict[str, Any] = {
    "staff": {"system": True, "grants": {"*": "all"}},
    "organizer": {
        "grants": {
            "testapp.event:view": "own",
            "testapp.event:change": "own",
            "testapp.event:delete": "own",
            "testapp.event:add": "all",
        }
    },
    "venue_manager": {
        "grants": {
            "testapp.event:view": "related:venue",
            "testapp.event:approve": "related:venue",
        }
    },
    "reader": {"grants": {"testapp.event:view": "all"}},
    "user": {"grants": {"testapp.customer:view": "all"}},
}


class GrantedEvents(BaseViewSet):
    """The default declaration: whatever KARNI_ROLES grants for Event."""

    model = Event
    access = Granted()

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        return Response({"id": str(self.get_object().pk)})


class DeclaredEvents(BaseViewSet):
    """A hand-written rule (EventHub's): published or yours or staff; only yours to change."""

    model = Event
    access = Access(
        read=PUBLISHED | Owned("organizer") | HasRole("staff"),
        write=Owned("organizer") | HasRole("staff"),
        create=HasRole("organizer", "staff"),
    )

    @action(detail=True, methods=["get"], access=Owned("organizer") | HasRole("staff"))
    def dashboard(self, request: Request, pk: str | None = None) -> Response:
        return Response({"id": str(self.get_object().pk)})


class GuardedEvents(BaseViewSet):
    """Readable by anyone signed in; the ``tests.why`` veto refuses deletes by readers."""

    model = Event
    access = Access(read=Authenticated(), write=Authenticated())


class MisownedEvents(BaseViewSet):
    """The slip ``why-empty`` names: the rule walks to the audit stamp, not the owner."""

    model = Event
    access = Access(read=Owned("created_by"), write=Owned("created_by"))


class OpenEvents(BaseViewSet):
    """Unscoped: plain DRF permission classes decide."""

    model = Event
    access = Unscoped(reason="the why tests' unscoped case")
    permission_classes = [IsAuthenticated]


class Customers(BaseViewSet):
    """Field-level visibility: Customer.Karni.field_roles."""

    model = Customer
    access = Access(read=Authenticated(), write=Authenticated())


def router() -> KarniRouter:
    found = KarniRouter()
    found.register("granted-events", GrantedEvents, basename="granted-events")
    found.register("declared-events", DeclaredEvents, basename="declared-events")
    found.register("guarded-events", GuardedEvents, basename="guarded-events")
    found.register("open-events", OpenEvents, basename="open-events")
    found.register("misowned-events", MisownedEvents, basename="misowned-events")
    found.register("customers", Customers, basename="customers")
    return found


def no_reader_deletes(context: Any) -> str | None:
    """The veto ``tests.why`` registers: readers may not delete through GuardedEvents."""
    if not isinstance(context.view, GuardedEvents) or context.action != "destroy":
        return None
    user = getattr(context.request, "user", None)
    if user is not None and user.groups.filter(name="reader").exists():
        return "Readers may not delete events (tests.why veto)."
    return None
