"""``karni.vetoes``: a registered veto refuses an action at the API and admin gates."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from karni.api import Access, Authenticated, BaseViewSet
from karni.vetoes import VetoContext, check_vetoes, register_veto, unregister_veto, vetoes
from tests.testapp.models import Venue

pytestmark = pytest.mark.django_db


class VenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Authenticated(), write=Authenticated())


@pytest.fixture
def no_deletes() -> Any:
    seen: list[VetoContext] = []

    def veto(context: VetoContext) -> str | None:
        seen.append(context)
        blocked = {"destroy", "delete", "delete_selected", "export", "export_csv", "import"}
        if context.names() & blocked:
            return f"{context.action} is blocked by the test veto."
        return None

    register_veto(veto, name="tests.no_deletes")
    yield seen
    unregister_veto("tests.no_deletes")


def test_registry_and_context_names(no_deletes: Any) -> None:
    assert "tests.no_deletes" in vetoes()
    context = VetoContext(None, "api", "destroy", model=Venue, permission="testapp.venue:delete")
    expected = {"destroy", "testapp.venue:delete", "testapp.venue", "testapp.venue:destroy"}
    assert context.names() == expected
    assert check_vetoes(context) == "destroy is blocked by the test veto."
    assert check_vetoes(VetoContext(None, "api", "list", model=Venue)) is None


def test_the_api_gate_refuses_a_vetoed_action(no_deletes: Any) -> None:
    user = get_user_model().objects.create_user(email="u@example.com", password="s3cret-pass-123")
    venue = Venue.objects.create(name="Arena", city="Berlin")
    request = APIRequestFactory().delete(f"/venues/{venue.pk}/")
    force_authenticate(request, user=user)
    response = VenueViewSet.as_view({"delete": "destroy"})(request, pk=str(venue.pk))
    assert response.status_code == 403 and "blocked by the test veto" in str(response.data)
    assert Venue.objects.filter(pk=venue.pk).exists()
    request = APIRequestFactory().get("/venues/")
    force_authenticate(request, user=user)
    assert VenueViewSet.as_view({"get": "list"})(request).status_code == 200
    request = APIRequestFactory().get("/venues/export/")
    force_authenticate(request, user=user)
    export = VenueViewSet.as_view({"get": "export"}, **VenueViewSet.export.kwargs)(request)
    assert export.status_code == 403
    assert any(c.kind == "api" and c.permission == "testapp.venue:delete" for c in no_deletes)


def test_the_admin_hides_vetoed_permissions_and_actions(no_deletes: Any) -> None:
    if Venue not in admin.site._registry:
        pytest.skip("Venue is not registered on the default admin site")
    root = get_user_model().objects.create_superuser(
        email="root@example.com", password="s3cret-pass-123"
    )
    venue = Venue.objects.create(name="Arena", city="Berlin")
    client = Client()
    client.force_login(root)
    page = client.get(reverse("admin:testapp_venue_changelist"))
    body = page.content.decode()
    assert 'value="delete_selected"' not in body and 'value="export_csv"' not in body
    assert 'value="export_xlsx"' in body  # not vetoed: still offered
    assert client.get(reverse("admin:testapp_venue_delete", args=[venue.pk])).status_code == 403
    assert client.get(reverse("admin:testapp_venue_import")).status_code == 403
    assert client.get(reverse("admin:testapp_venue_change", args=[venue.pk])).status_code == 200
