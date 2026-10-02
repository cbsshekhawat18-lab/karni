"""Permission behaviour of BaseViewSet: conf defaults + ObjectPermissionsMixin."""

from __future__ import annotations

from typing import Any

import pytest
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.permissions import BasePermission
from rest_framework.test import APIRequestFactory, force_authenticate

from tests.testapp.models import Event
from tests.testapp.viewsets import EventViewSet

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_throttle_state() -> Any:
    yield
    cache.clear()


@pytest.fixture
def user() -> Any:
    return get_user_model().objects.create_user(
        email="permissions@example.com", password="a-strong-password-123"
    )


class _DenyObjects(BasePermission):
    message = "denied by test object permission"

    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        return False


class _AllowObjects(BasePermission):
    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        return True


class _DenyingViewSet(EventViewSet):
    object_permission_classes = [_DenyObjects]


class _AllowingViewSet(EventViewSet):
    object_permission_classes = [_AllowObjects]


class _PublicOnlyViewSet(EventViewSet):
    def filter_queryset_for_user(self, qs: Any) -> Any:
        return qs.filter(is_public=True)


def _status_value() -> str:
    return list(Event._meta.get_field("status").choices)[0][0]


def _event(title: str = "Event", **kwargs: Any) -> Event:
    kwargs.setdefault("starts_at", timezone.now())
    kwargs.setdefault("status", _status_value())
    return Event.objects.create(title=title, **kwargs)


def test_conf_default_permission_is_authenticated_or_read_only() -> None:
    assert django_settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly"
    ]


def test_anonymous_list_is_allowed() -> None:
    _event()
    response = EventViewSet.as_view({"get": "list"})(APIRequestFactory().get("/"))
    assert response.status_code == 200
    assert response.data["count"] == 1


def test_anonymous_retrieve_is_allowed() -> None:
    event = _event()
    response = EventViewSet.as_view({"get": "retrieve"})(
        APIRequestFactory().get("/"), pk=str(event.pk)
    )
    assert response.status_code == 200
    assert response.data["id"] == str(event.pk)


def test_anonymous_create_is_rejected() -> None:
    response = EventViewSet.as_view({"post": "create"})(
        APIRequestFactory().post("/", {"title": "Nope"}, format="json")
    )
    # 401 with WWW-Authenticate-capable authenticators, 403 otherwise.
    assert response.status_code in (401, 403)
    assert Event.objects.count() == 0


def test_anonymous_delete_is_rejected() -> None:
    event = _event()
    response = EventViewSet.as_view({"delete": "destroy"})(
        APIRequestFactory().delete("/"), pk=str(event.pk)
    )
    assert response.status_code in (401, 403)
    assert Event.objects.filter(pk=event.pk).exists()


def test_object_permission_classes_deny_detail_access(user: Any) -> None:
    event = _event()
    request = APIRequestFactory().get("/")
    force_authenticate(request, user=user)
    response = _DenyingViewSet.as_view({"get": "retrieve"})(request, pk=str(event.pk))
    assert response.status_code == 403


def test_object_permission_classes_allow_detail_access(user: Any) -> None:
    event = _event()
    request = APIRequestFactory().get("/")
    force_authenticate(request, user=user)
    response = _AllowingViewSet.as_view({"get": "retrieve"})(request, pk=str(event.pk))
    assert response.status_code == 200


def test_object_permissions_do_not_affect_list(user: Any) -> None:
    _event()
    request = APIRequestFactory().get("/")
    force_authenticate(request, user=user)
    response = _DenyingViewSet.as_view({"get": "list"})(request)
    assert response.status_code == 200
    assert response.data["count"] == 1


def test_filter_queryset_for_user_hook_scopes_the_queryset(user: Any) -> None:
    visible = _event("Visible", is_public=True)
    _event("Hidden", is_public=False)
    request = APIRequestFactory().get("/")
    force_authenticate(request, user=user)
    response = _PublicOnlyViewSet.as_view({"get": "list"})(request)
    assert response.status_code == 200
    assert {row["id"] for row in response.data["results"]} == {str(visible.pk)}
