"""Permission posture of BaseViewSet: the access gate, conf defaults, legacy hooks.

The per-predicate behaviour lives in ``test_access.py``; this module pins how
the access declaration interacts with DRF's permission machinery
(``DEFAULT_PERMISSION_CLASSES``, ``permission_classes``) and with the
``ObjectPermissionsMixin`` hooks BaseViewSet still carries.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.permissions import BasePermission
from rest_framework.test import APIRequestFactory, force_authenticate

from karni.api import Access, Authenticated, BaseViewSet, Public
from karni.deprecation import KarniDeprecationWarning
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


class _DenyAll(BasePermission):
    message = "denied by an extra permission class"

    def has_permission(self, request: Any, view: Any) -> bool:
        return False


with pytest.warns(KarniDeprecationWarning, match="object_permission_classes"):

    class _DenyingViewSet(EventViewSet):
        object_permission_classes = [_DenyObjects]


with pytest.warns(KarniDeprecationWarning, match="object_permission_classes"):

    class _AllowingViewSet(EventViewSet):
        object_permission_classes = [_AllowObjects]


class _PublicOnlyViewSet(EventViewSet):
    # karni: allow(access-override): exercises the legacy hook in tests
    def filter_queryset_for_user(self, qs: Any) -> Any:
        return qs.filter(is_public=True)


class _ExtraGateViewSet(EventViewSet):
    permission_classes = [_DenyAll]


def _status_value() -> str:
    return list(Event._meta.get_field("status").choices)[0][0]


def _event(title: str = "Event", **kwargs: Any) -> Event:
    kwargs.setdefault("starts_at", timezone.now())
    kwargs.setdefault("status", _status_value())
    return Event.objects.create(title=title, **kwargs)


def _authed(request: Any, user: Any) -> Any:
    force_authenticate(request, user=user)
    return request


# --- conf defaults ---------------------------------------------------------------


def test_conf_default_permission_is_authenticated() -> None:
    """The DRF fallback (plain views, Unscoped viewsets) fails closed for anonymous."""
    assert django_settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticated"
    ]


def test_drf_default_does_not_apply_to_access_viewsets() -> None:
    # EventViewSet declares read=Public(): anonymous reads pass even though the
    # project-wide DRF default requires authentication.
    _event()
    response = EventViewSet.as_view({"get": "list"})(APIRequestFactory().get("/"))
    assert response.status_code == 200
    assert response.data["count"] == 1


@override_settings(
    REST_FRAMEWORK={
        **django_settings.REST_FRAMEWORK,
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    }
)
def test_a_permissive_drf_default_cannot_open_an_access_viewset() -> None:
    response = EventViewSet.as_view({"post": "create"})(
        APIRequestFactory().post("/", {"title": "Nope"}, format="json")
    )
    assert response.status_code in (401, 403)
    assert Event.objects.count() == 0


# --- the gate as seen through EventViewSet (read=Public, write=Authenticated) ------


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


def test_permission_classes_are_anded_after_the_gate(user: Any) -> None:
    _event()
    request = _authed(APIRequestFactory().get("/"), user)
    response = _ExtraGateViewSet.as_view({"get": "list"})(request)
    assert response.status_code == 403
    assert "extra permission class" in str(response.data["detail"])


# --- legacy ObjectPermissionsMixin hooks (deprecated object_permission_classes) ----


def test_object_permission_classes_still_deny_detail_access(user: Any) -> None:
    event = _event()
    request = _authed(APIRequestFactory().get("/"), user)
    response = _DenyingViewSet.as_view({"get": "retrieve"})(request, pk=str(event.pk))
    assert response.status_code == 403


def test_object_permission_classes_still_allow_detail_access(user: Any) -> None:
    event = _event()
    request = _authed(APIRequestFactory().get("/"), user)
    response = _AllowingViewSet.as_view({"get": "retrieve"})(request, pk=str(event.pk))
    assert response.status_code == 200


def test_object_permissions_do_not_affect_list(user: Any) -> None:
    _event()
    request = _authed(APIRequestFactory().get("/"), user)
    response = _DenyingViewSet.as_view({"get": "list"})(request)
    assert response.status_code == 200
    assert response.data["count"] == 1


def test_filter_queryset_for_user_hook_scopes_the_queryset(user: Any) -> None:
    visible = _event("Visible", is_public=True)
    _event("Hidden", is_public=False)
    request = _authed(APIRequestFactory().get("/"), user)
    response = _PublicOnlyViewSet.as_view({"get": "list"})(request)
    assert response.status_code == 200
    assert {row["id"] for row in response.data["results"]} == {str(visible.pk)}


def test_filter_queryset_for_user_runs_after_the_read_scope(user: Any) -> None:
    class _OwnPublicViewSet(BaseViewSet):
        model = Event
        access = Access(read=Authenticated(), write=Authenticated())

        # karni: allow(access-override): receives the access-scoped queryset
        def filter_queryset_for_user(self, qs: Any) -> Any:
            return qs.filter(is_public=True)

    _event("Hidden", is_public=False)
    shown = _event("Shown", is_public=True)
    anonymous = _OwnPublicViewSet.as_view({"get": "list"})(APIRequestFactory().get("/"))
    assert anonymous.status_code in (401, 403)  # the gate runs before any row hook
    request = _authed(APIRequestFactory().get("/"), user)
    response = _OwnPublicViewSet.as_view({"get": "list"})(request)
    assert [row["id"] for row in response.data["results"]] == [str(shown.pk)]


def test_public_predicate_is_the_explicit_public_form() -> None:
    class _CatalogueViewSet(BaseViewSet):
        model = Event
        access = Access(read=Public(), write=Authenticated())

    _event()
    response = _CatalogueViewSet.as_view({"get": "list"})(APIRequestFactory().get("/"))
    assert response.status_code == 200
