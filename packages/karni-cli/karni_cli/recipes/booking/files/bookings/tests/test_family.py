"""The booking part in a family: its settings section and its connection, on and off."""

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps
from django.utils import timezone
from karni import preferences
from karni.testing.factories import create
from karni_payments.models import Payment, Refund
from karni_payments.providers.test import TestProvider

from bookings.models import Booking, Resource, Slot

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _test_payments(settings: Any) -> None:
    settings.KARNI_PAYMENTS_PROVIDER = "test"
    TestProvider.reset()


def _paid_booking(client: Any, hours: int) -> dict[str, Any]:
    start = timezone.now() + dt.timedelta(hours=hours)
    slot = create(
        Slot,
        resource=create(Resource, price=Decimal("30.00")),
        capacity=5,
        starts_at=start,
        ends_at=start + dt.timedelta(hours=1),
    )
    booking = client.post(
        "/api/bookings/", {"slot": str(slot.pk)}, format="json"
    ).json()
    paid = client.post(f"/api/bookings/{booking['id']}/pay/")
    payment = Payment.objects.get(pk=paid.json()["payment"])
    payment.status = Payment.Status.SUCCEEDED  # the provider's webhook
    payment.save()
    return booking


def test_the_section_is_registered_with_its_default() -> None:
    assert preferences.value("bookings.refund_notice_hours", -1) == 0
    section = preferences.get("bookings")
    assert section.refund_notice_hours == 0  # type: ignore[attr-defined]


def test_a_late_cancel_is_not_refunded_under_a_notice(client_as: Any) -> None:
    client = client_as("customer")
    late = _paid_booking(client, hours=10)
    early = _paid_booking(client, hours=72)
    with preferences.override(bookings={"refund_notice_hours": 24}):
        cancelled = client.post(f"/api/bookings/{late['id']}/cancel/").json()
        assert cancelled["status"] == "cancelled" and cancelled["refund"] is None
        refunded = client.post(f"/api/bookings/{early['id']}/cancel/").json()
        assert refunded["refund"]["amount"] == "30.00"
    assert Refund.objects.count() == 1


def test_staff_change_the_notice_in_settings(client_as: Any) -> None:
    staff = client_as("bookings-staff")
    url = "/api/preferences/sections/bookings/"
    changed = staff.patch(url, {"refund_notice_hours": 12}, format="json")
    assert changed.status_code == 200, changed.content
    assert preferences.value("bookings.refund_notice_hours", 0) == 12
    refused = staff.patch(url, {"refund_notice_hours": -1}, format="json")
    assert refused.status_code == 400 and refused.json()["code"] == "E323"
    member = client_as("customer")
    assert (
        member.patch(url, {"refund_notice_hours": 0}, format="json").status_code == 403
    )


def test_bookings_are_published_while_the_connection_is_on(client_as: Any) -> None:
    if not apps.is_installed("karni.outbox"):  # alone: the connection stays off
        assert not preferences.active("bookings.family_events")
        return
    from karni.testing import capture_events

    staff = client_as("bookings-staff")
    booking = _paid_booking(client_as("customer"), hours=48)
    with capture_events() as events:
        staff.post(f"/api/bookings/{booking['id']}/cancel/")
    assert [e.name for e in events] == ["bookings.booking.cancelled"]
    other = _paid_booking(client_as("customer"), hours=48)
    with (
        preferences.override(connections={"bookings.family_events": False}),
        capture_events() as events,
    ):
        staff.post(f"/api/bookings/{other['id']}/cancel/")
    assert len(events) == 0
