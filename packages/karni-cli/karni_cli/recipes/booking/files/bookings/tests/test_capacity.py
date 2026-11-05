"""The booking rules: a slot takes no more than its capacity, and payment confirms."""

from typing import Any

import pytest
from karni.testing.factories import create
from karni_payments.models import Payment
from karni_payments.providers.test import TestProvider

from bookings.models import Booking, Slot

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _test_payments(settings: Any) -> None:
    settings.KARNI_PAYMENTS_PROVIDER = "test"
    TestProvider.reset()


def test_a_slot_never_takes_more_bookings_than_its_capacity(client_as: Any) -> None:
    slot = create(Slot, capacity=2)
    client = client_as("member")
    first, second = (
        client.post("/api/bookings/", {"slot": str(slot.pk)}) for _ in range(2)
    )
    assert first.status_code == second.status_code == 201, first.content
    full = client.post("/api/bookings/", {"slot": str(slot.pk)})
    assert full.status_code == 409 and full.json()["code"] == "E985"
    cancelled = client.post(f"/api/bookings/{first.json()['id']}/cancel/")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    slot.refresh_from_db()
    assert slot.remaining == 1
    assert client.post("/api/bookings/", {"slot": str(slot.pk)}).status_code == 201


def test_a_paid_booking_is_confirmed(client_as: Any) -> None:
    client = client_as("member")
    booked = client.post("/api/bookings/", {"slot": str(create(Slot, capacity=5).pk)})
    paid = client.post(f"/api/bookings/{booked.json()['id']}/pay/")
    assert paid.status_code == 200, paid.content
    payment = Payment.objects.get(pk=paid.json()["payment"])
    payment.status = Payment.Status.SUCCEEDED  # what the provider's webhook does
    payment.save()
    assert Booking.objects.get(pk=booked.json()["id"]).status == "confirmed"
