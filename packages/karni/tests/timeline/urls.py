"""The timeline's URLconf for its tests: the people resources, two parts' resources, the timeline.

The core suite sets ``KARNI_TIMELINE_API = False`` (and ``KARNI_PEOPLE_API =
False``) so the test app's OpenAPI snapshot stays as it is. These tests use
``ROOT_URLCONF="tests.timeline.urls"`` and
``KARNI_API_ROUTER="tests.timeline.urls.get_router"``.
"""

from __future__ import annotations

from django.urls import include, path

from karni.api import BaseViewSet, Granted
from karni.api.routers import KarniRouter
from karni.people.viewsets import OrganisationViewSet, PersonViewSet
from karni.timeline.api import TimelineView
from tests.helpdeskapp.models import Ticket
from tests.loyaltyapp.models import Visit


class TicketViewSet(BaseViewSet):
    """The help desk's tickets: a customer reads their own (``owner_field`` person__user)."""

    model = Ticket
    access = Granted()
    route = "tickets"
    auto_register = False


class VisitViewSet(BaseViewSet):
    """The loyalty part's visits: a customer reads their own."""

    model = Visit
    access = Granted()
    route = "visits"
    auto_register = False


def get_router() -> KarniRouter:
    """The resources the timeline checks entries against."""
    router = KarniRouter()
    router.register("people", PersonViewSet, basename="people-person")
    router.register("organisations", OrganisationViewSet, basename="people-organisation")
    router.register("tickets", TicketViewSet, basename="tickets")
    router.register("visits", VisitViewSet, basename="visits")
    return router


urlpatterns = [
    path("api/auth/", include("karni.accounts.urls")),
    path("api/timeline/", TimelineView.as_view(), name="timeline-test"),
    path("api/", include(get_router().urls)),
]
