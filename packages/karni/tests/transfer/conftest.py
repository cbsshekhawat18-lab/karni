"""Shared fixtures for the import/export suite: a project's roles, users, viewsets and files."""

from __future__ import annotations

import io
from typing import Any

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.api import Access, Authenticated, BaseViewSet, Granted, Owned
from karni.api.routers import KarniRouter
from karni.transfer.formats import xlsx_bytes
from tests.testapp.models import Event, Tag, Venue

PROJECT_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "organizer": {
        "name": "Organizer",
        "grants": {
            "testapp.event:view": "own",
            "testapp.event:change": "own",
            "testapp.event:add": "all",
            "testapp.venue:view": "all",
            "testapp.tag:view": "all",
        },
    },
    "venue_manager": {
        "name": "Venue manager",
        "grants": {
            "testapp.event:view": "related:venue",
            "testapp.event:change": "related:venue",
            "testapp.event:add": "related:venue",
            "testapp.venue:view": "all",
            "testapp.tag:view": "all",
        },
    },
    "reader": {"grants": {"testapp.event:view": "all", "testapp.venue:view": "all"}},
}


class EventViewSet(BaseViewSet):
    model = Event
    access = Granted()
    search_fields = ["title"]
    filterset_fields = ["status", "venue"]


class VenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Authenticated(), write=Authenticated())


class TagViewSet(BaseViewSet):
    model = Tag
    access = Access(read=Authenticated(), write=Owned("created_by"))


def build_router() -> KarniRouter:
    router = KarniRouter()
    router.register("events", EventViewSet, basename="events")
    router.register("venues", VenueViewSet, basename="venues")
    router.register("tags", TagViewSet, basename="tags")
    return router


@pytest.fixture(autouse=True)
def _project(settings: Any) -> None:
    """The project's roles, through pytest-django's ``settings`` so every override unwinds in order.

    (A manual ``override_settings`` here plus a test that sets ``settings.X``
    would be disabled out of order and leak ``KARNI_ROLES`` into later tests.)
    """
    settings.KARNI_ROLES = PROJECT_ROLES
    sync_roles()


@pytest.fixture(autouse=True)
def _routed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the test viewsets the routed ones (relation scoping, the importer, the admin)."""
    from karni.api import routers

    router = build_router()
    monkeypatch.setattr(routers, "get_default_router", lambda: router)
    # resolve_router() caches by factory path; a warm cache from earlier tests must not win.
    monkeypatch.setattr(routers, "_RESOLVED_ROUTERS", {routers.DEFAULT_ROUTER_FACTORY: router})


@pytest.fixture
def make_user(django_user_model: Any) -> Any:
    def _make(email: str, *roles: str, superuser: bool = False, **attrs: Any) -> Any:
        if superuser:
            return django_user_model.objects.create_superuser(
                email=email, password="s3cret-pass-123"
            )
        user = django_user_model.objects.create_user(
            email=email, password="s3cret-pass-123", **attrs
        )
        for slug in roles:
            assign_role(user, slug)
        return user

    return _make


@pytest.fixture
def venues() -> dict[str, Venue]:
    return {
        "arena": Venue.objects.create(name="Arena", city="Berlin"),
        "hall": Venue.objects.create(name="Hall", city="Paris"),
    }


def csv_file(name: str, rows: list[list[Any]]) -> Any:
    from django.core.files.uploadedfile import SimpleUploadedFile

    text = "\n".join(",".join(str(cell) for cell in row) for row in rows) + "\n"
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


def xlsx_file(name: str, rows: list[list[Any]]) -> Any:
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(
        name,
        xlsx_bytes([("Data", rows)]),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def api_request(method: str, path: str, user: Any, data: Any = None, **extra: Any) -> Any:
    factory = APIRequestFactory()
    request = getattr(factory, method)(path, data, **extra)
    force_authenticate(request, user=user)
    request.user = user  # the services read request.user directly, like the admin does
    return request


def call(viewset: type[Any], actions: dict[str, str], request: Any, **kwargs: Any) -> Any:
    """Dispatch like the router would: the ``@action``'s own kwargs (renderers) apply."""
    initkwargs: dict[str, Any] = {}
    for name in actions.values():
        initkwargs.update(getattr(getattr(viewset, name, None), "kwargs", {}) or {})
    response = viewset.as_view(actions, **initkwargs)(request, **kwargs)
    if hasattr(response, "render") and not getattr(response, "is_rendered", True):
        response.render()
    return response


def read_csv(response: Any) -> list[list[str]]:
    import csv

    content = b"".join(response.streaming_content) if response.streaming else response.content
    return [row for row in csv.reader(io.StringIO(content.decode("utf-8")))]
