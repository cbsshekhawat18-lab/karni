"""``karni.signals.pre_write``: sent before every BaseModel write; a receiver may defer it."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from karni.api import Access, Authenticated, BaseViewSet
from karni.exceptions import KarniWriteDeferred
from karni.signals import pre_write
from tests.testapp.models import Venue

pytestmark = pytest.mark.django_db


class VenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Authenticated(), write=Authenticated())


@pytest.fixture
def seen() -> Any:
    calls: list[tuple[str, Any]] = []

    def receiver(
        sender: Any, instance: Any, action: str, update_fields: Any, **kwargs: Any
    ) -> None:
        calls.append((action, instance.name))

    pre_write.connect(receiver, sender=Venue, dispatch_uid="tests.pre_write.seen")
    yield calls
    pre_write.disconnect(dispatch_uid="tests.pre_write.seen", sender=Venue)


@pytest.fixture
def deferring() -> Any:
    def receiver(sender: Any, instance: Any, action: str, **kwargs: Any) -> None:
        if instance.city == "Hold":
            raise KarniWriteDeferred(
                f"{instance.name} was held for review.",
                payload={"held": instance.name, "action": action},
            )

    pre_write.connect(receiver, sender=Venue, dispatch_uid="tests.pre_write.defer")
    yield
    pre_write.disconnect(dispatch_uid="tests.pre_write.defer", sender=Venue)


def test_sent_once_per_create_update_and_delete(seen: Any) -> None:
    venue = Venue.objects.create(name="Arena", city="Berlin")
    venue.city = "Paris"
    venue.save()
    venue.delete()  # a soft delete saves deleted_at: still one "delete" send, not an "update"
    assert seen == [("create", "Arena"), ("update", "Arena"), ("delete", "Arena")]
    venue.restore()
    assert seen[-1] == ("update", "Arena")


def test_a_deferred_write_never_touches_the_row(deferring: Any) -> None:
    venue = Venue.objects.create(name="Arena", city="Berlin")
    venue.city = "Hold"
    with pytest.raises(KarniWriteDeferred) as caught:
        venue.save()
    assert caught.value.payload == {"held": "Arena", "action": "update"}
    assert caught.value.status == 202
    venue.refresh_from_db()
    assert venue.city == "Berlin"
    with pytest.raises(KarniWriteDeferred):
        Venue.objects.create(name="New", city="Hold")
    assert not Venue.objects.filter(name="New").exists()


def test_the_api_answers_202_with_the_payload(deferring: Any) -> None:
    user = get_user_model().objects.create_user(email="u@example.com", password="s3cret-pass-123")
    venue = Venue.objects.create(name="Arena", city="Berlin")
    request = APIRequestFactory().patch(f"/venues/{venue.pk}/", {"city": "Hold"}, format="json")
    force_authenticate(request, user=user)
    response = VenueViewSet.as_view({"patch": "partial_update"})(request, pk=str(venue.pk))
    assert response.status_code == 202 and response.data == {"held": "Arena", "action": "update"}
    venue.refresh_from_db()
    assert venue.city == "Berlin"
    request = APIRequestFactory().post("/venues/", {"name": "New", "city": "Hold"}, format="json")
    force_authenticate(request, user=user)
    response = VenueViewSet.as_view({"post": "create"})(request)
    assert response.status_code == 202 and response.data["action"] == "create"
    request = APIRequestFactory().patch(f"/venues/{venue.pk}/", {"city": "Rome"}, format="json")
    force_authenticate(request, user=user)
    response = VenueViewSet.as_view({"patch": "partial_update"})(request, pk=str(venue.pk))
    assert response.status_code == 200  # an undeferred write is as before


def test_the_admin_shows_the_message_and_writes_nothing(deferring: Any) -> None:
    if Venue not in admin.site._registry:
        pytest.skip("Venue is not registered on the default admin site")
    root = get_user_model().objects.create_superuser(
        email="root@example.com", password="s3cret-pass-123"
    )
    venue = Venue.objects.create(name="Arena", city="Berlin")
    client = Client()
    client.force_login(root)
    response = client.post(
        reverse("admin:testapp_venue_change", args=[venue.pk]),
        {"name": "Arena", "city": "Hold"},
        follow=True,
    )
    assert response.status_code == 200
    assert "was held for review" in response.content.decode()
    venue.refresh_from_db()
    assert venue.city == "Berlin"
    response = client.post(
        reverse("admin:testapp_venue_add"), {"name": "New", "city": "Hold"}, follow=True
    )
    assert "was held for review" in response.content.decode()
    assert not Venue.objects.filter(name="New").exists()
