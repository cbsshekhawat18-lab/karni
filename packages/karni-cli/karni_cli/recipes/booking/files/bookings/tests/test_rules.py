"""The booking rules of karni.yaml: what a member or staff may send, and what is refused."""

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from karni.rules import unchecked
from karni.testing.api import user_with_roles
from karni.testing.factories import create
from karni_payments.models import Payment, Refund
from karni_payments.providers.test import TestProvider

from bookings.models import Booking, Resource, Slot

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _test_payments(settings: Any) -> None:
    settings.KARNI_PAYMENTS_PROVIDER = "test"
    TestProvider.reset()


def _slot(**values: Any) -> Slot:
    start = timezone.now() + dt.timedelta(days=2)
    values.setdefault("resource", create(Resource, price=Decimal("30.00")))
    values.setdefault("capacity", 5)
    return create(Slot, starts_at=start, ends_at=start + dt.timedelta(hours=1), **values)


def _book(client: Any, slot: Slot, **extra: Any) -> Any:
    return client.post("/api/bookings/", {"slot": str(slot.pk), **extra}, format="json")


def _code(response: Any, field: str) -> str:
    return str(response.json()[field][0])[:4]


def test_a_booking_keeps_its_slot(client_as: Any) -> None:
    """PATCH of the slot was 200 and left both slots' places wrong (then cancel was a 500)."""
    client = client_as("member")
    first, second = _slot(), _slot()
    booking = _book(client, first).json()
    moved = client.patch(f"/api/bookings/{booking['id']}/", {"slot": str(second.pk)})
    assert moved.status_code == 400 and _code(moved, "slot") == "E994"
    cancelled = client.post(f"/api/bookings/{booking['id']}/cancel/")
    assert cancelled.status_code == 200, cancelled.content
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.remaining == 5 and second.remaining == 5


def test_a_member_books_only_for_themselves(client_as: Any) -> None:
    other = user_with_roles("member")
    client = client_as("member")
    refused = _book(client, _slot(), member=str(other.pk))
    assert refused.status_code == 403 and refused.json()["detail"].startswith("E135: ")
    staff = client_as("staff").post(
        "/api/bookings/", {"slot": str(_slot().pk), "member": str(other.pk)}, format="json"
    )
    assert staff.status_code == 201, staff.content
    assert Booking.objects.get(pk=staff.json()["id"]).member == other


def test_a_member_books_a_slot_once(client_as: Any) -> None:
    client = client_as("member")
    slot = _slot()
    first = _book(client, slot)
    again = _book(client, slot)
    assert again.status_code == 400 and _code(again, "slot") == "E991"
    client.post(f"/api/bookings/{first.json()['id']}/cancel/")
    assert _book(client, slot).status_code == 201  # a cancelled booking does not count


def test_a_started_slot_cannot_be_booked(client_as: Any) -> None:
    start = timezone.now() - dt.timedelta(minutes=30)
    with unchecked(reason="test: a slot that has started"):
        slot = create(Slot, starts_at=start, ends_at=start + dt.timedelta(hours=1), capacity=5)
    refused = _book(client_as("member"), slot)
    assert refused.status_code == 400 and _code(refused, "slot") == "E993"


def test_pay_twice_opens_one_payment_and_a_cancelled_booking_is_not_paid(
    client_as: Any,
) -> None:
    client = client_as("member")
    booking = _book(client, _slot()).json()
    first = client.post(f"/api/bookings/{booking['id']}/pay/")
    second = client.post(f"/api/bookings/{booking['id']}/pay/")
    assert first.status_code == second.status_code == 200, second.content
    assert first.json() == second.json()
    assert Payment.objects.count() == 1
    client.post(f"/api/bookings/{booking['id']}/cancel/")
    refused = client.post(f"/api/bookings/{booking['id']}/pay/")
    assert refused.status_code == 409 and refused.json()["code"] == "E997"


def test_a_paid_booking_is_not_paid_again_and_its_cancel_refunds(client_as: Any) -> None:
    client = client_as("member")
    booking = _book(client, _slot()).json()
    paid = client.post(f"/api/bookings/{booking['id']}/pay/")
    payment = Payment.objects.get(pk=paid.json()["payment"])
    payment.status = Payment.Status.SUCCEEDED  # the provider's webhook
    payment.save()
    assert Booking.objects.get(pk=booking["id"]).status == "confirmed"
    again = client.post(f"/api/bookings/{booking['id']}/pay/")
    assert again.status_code == 409 and again.json()["code"] == "E997"
    cancelled = client.post(f"/api/bookings/{booking['id']}/cancel/")
    assert cancelled.status_code == 200, cancelled.content
    assert cancelled.json()["refund"]["amount"] == "30.00"
    assert Refund.objects.filter(payment=payment).count() == 1


def test_staff_confirm_and_delete_members_cancel(client_as: Any) -> None:
    member = client_as("member")
    booking = _book(member, _slot()).json()
    assert member.post(f"/api/bookings/{booking['id']}/confirm/").status_code == 403
    assert member.delete(f"/api/bookings/{booking['id']}/").status_code == 403
    confirmed = client_as("staff").post(f"/api/bookings/{booking['id']}/confirm/")
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"


def test_a_slot_with_live_bookings_is_not_deleted(client_as: Any) -> None:
    slot = _slot()
    booking = _book(client_as("member"), slot).json()
    staff = client_as("staff")
    refused = staff.delete(f"/api/slots/{slot.pk}/")
    assert refused.status_code == 409 and refused.json()["code"] == "E995"
    staff.post(f"/api/bookings/{booking['id']}/cancel/")
    assert staff.delete(f"/api/slots/{slot.pk}/").status_code == 204


def test_prices_and_capacities_keep_their_bounds(client_as: Any) -> None:
    staff = client_as("staff")
    price = staff.post("/api/resources/", {"name": "Room", "price": "-5"}, format="json")
    assert price.status_code == 400 and _code(price, "price") == "E990"
    resource = create(Resource, price=Decimal("10.00"))
    start = timezone.now() + dt.timedelta(days=1)
    slot = {
        "resource": str(resource.pk),
        "starts_at": start.isoformat(),
        "ends_at": (start + dt.timedelta(hours=1)).isoformat(),
        "capacity": 0,
    }
    empty = staff.post("/api/slots/", slot, format="json")
    assert empty.status_code == 400 and _code(empty, "capacity") == "E990"
    past = {**slot, "capacity": 2, "starts_at": "2001-01-01T09:00:00Z"}
    assert _code(staff.post("/api/slots/", past, format="json"), "starts_at") == "E990"


def test_the_member_hears_of_a_confirmed_and_a_cancelled_booking(
    client_as: Any, mailoutbox: list[Any], django_capture_on_commit_callbacks: Any
) -> None:
    member = client_as("member")
    booking = _book(member, _slot()).json()
    with django_capture_on_commit_callbacks(execute=True):
        client_as("staff").post(f"/api/bookings/{booking['id']}/confirm/")
    with django_capture_on_commit_callbacks(execute=True):
        member.post(f"/api/bookings/{booking['id']}/cancel/")
    subjects = [message.subject for message in mailoutbox]
    assert [subject.split(":")[0] for subject in subjects] == ["Booked", "Cancelled"]
    assert all(message.to == [member.user.email] for message in mailoutbox)
