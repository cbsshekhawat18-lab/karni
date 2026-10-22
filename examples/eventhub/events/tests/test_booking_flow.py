"""The money path: book → pay → provider webhook → confirmed → email; plus the organizer view."""

import json
from decimal import Decimal

import pytest
from django.core import mail
from karni.capacity import CapacityExceeded
from karni.lifecycle import IllegalTransition
from karni.testing.factories import create
from karni_payments.models import Payment
from karni_payments.providers.test import TestProvider

from events.models import Booking, TicketTier

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _in_process_payments(settings):
    settings.KARNI_PAYMENTS_PROVIDER = "test"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    TestProvider.reset()


def post_json(client, path, payload):
    return client.post(path, json.dumps(payload), content_type="application/json")


def book(client, tier, quantity=2):
    return post_json(
        client,
        "/api/bookings/",
        {"event": str(tier.event_id), "tier": str(tier.pk), "quantity": quantity},
    )


def test_an_attendee_books_pays_and_is_confirmed_by_the_webhook(
    client_as, django_capture_on_commit_callbacks
):
    tier = create(TicketTier, price=Decimal("25.00"), quantity=10)
    client = client_as("attendee")

    created = book(client, tier)
    assert created.status_code == 201, created.content
    booking = Booking.objects.get(pk=created.json()["id"])
    assert booking.attendee == client.user and booking.status == "pending"

    paid = client.post(f"/api/bookings/{booking.pk}/pay/")
    assert paid.status_code == 200, paid.content
    assert paid.json()["url"].startswith("https://checkout.test/")
    payment = Payment.objects.get(pk=paid.json()["payment"])
    assert payment.amount == Decimal("50.00") and payment.user == client.user

    body, headers = TestProvider.build_webhook(
        {
            "id": "evt_1",
            "type": "payment.succeeded",
            "status": "succeeded",
            "checkout_session_id": payment.checkout_session_id,
        }
    )
    with django_capture_on_commit_callbacks(execute=True):
        hook = client.post(
            "/payments/webhook/test/",
            body,
            content_type="application/json",
            headers={"X-Test-Signature": headers["X-Test-Signature"]},
        )
    assert hook.status_code < 300, hook.content

    booking.refresh_from_db()
    assert booking.status == "confirmed" and booking.confirmed_at is not None
    assert [m.to for m in mail.outbox] == [[client.user.email]]
    assert tier.event.title in mail.outbox[0].subject
    booking.refresh_from_db()
    assert booking.confirmation_sent_at is not None


def test_bookings_never_exceed_the_tier(client_as):
    tier = create(TicketTier, quantity=3)
    client = client_as("attendee")
    first = book(client, tier, quantity=3)
    assert first.status_code == 201
    over = book(client, tier, quantity=1)
    assert over.status_code == 409 and over.json()["code"] == "E985"  # the database refused it
    assert over.json()["conflict"]["remaining"] == 0 and "is sold out" in over.json()["detail"]
    # Cancelling gives the seats back; changing the tickets of a booking is refused.
    cancelled = client.post(f"/api/bookings/{first.json()['id']}/cancel/")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    tier.refresh_from_db()
    assert tier.remaining == 3
    again = book(client, tier, quantity=2)
    edit = client.patch(
        f"/api/bookings/{again.json()['id']}/", json.dumps({"quantity": 3}),
        content_type="application/json",
    )
    assert edit.status_code == 400 and "book again" in edit.json()["quantity"][0]
    assert client.delete(f"/api/bookings/{again.json()['id']}/").status_code == 204
    tier.refresh_from_db()
    assert tier.remaining == 3  # a deleted booking frees its seats too


def test_a_restored_booking_takes_its_seats_again(client_as):
    tier = create(TicketTier, quantity=3)
    client = client_as("attendee")
    booking = Booking.objects.get(pk=book(client, tier, quantity=2).json()["id"])
    booking.delete()
    tier.refresh_from_db()
    assert tier.remaining == 3  # deleting gave the seats back
    booking.restore()
    tier.refresh_from_db()
    assert tier.remaining == 1  # restoring took them again
    # Sold out in the meantime: the restore is refused and the booking stays deleted.
    booking.delete()
    assert book(client, tier, quantity=3).status_code == 201
    with pytest.raises(CapacityExceeded):
        booking.restore()
    assert booking.is_deleted
    booking.refresh_from_db()
    assert booking.is_deleted
    tier.refresh_from_db()
    assert tier.remaining == 0


def test_a_confirmed_booking_cannot_go_back_to_pending(client_as):
    tier = create(TicketTier, quantity=5)
    booking = Booking.objects.get(pk=book(client_as("attendee"), tier).json()["id"])
    booking.transition("status", "confirmed")
    with pytest.raises(IllegalTransition, match="legal transitions are: 'cancelled'"):
        booking.transition("status", "pending")


def test_only_published_events_take_bookings(client_as):
    # Karni's relation scoping rejects the draft's pk first (an attendee cannot
    # read it); the serializer rule is the backstop for organizers and staff.
    tier = create(TicketTier, event__status="draft")
    response = book(client_as("attendee"), tier)
    assert response.status_code == 400 and "event" in response.json()
    assert Booking.objects.count() == 0
    organizer = client_as(user=tier.event.organizer)
    assert "published" in book(organizer, tier).json()["event"][0]


def test_the_checkout_validator_refuses_any_other_amount(client_as):
    tier = create(TicketTier, price=Decimal("25.00"))
    client = client_as("attendee")
    booking = Booking.objects.get(pk=book(client, tier).json()["id"])
    forged = post_json(
        client,
        "/api/payments/checkout/",
        {
            "amount": "1.00",
            "success_url": "http://localhost:5173/x",
            "cancel_url": "http://localhost:5173/x",
            "metadata": {"booking": str(booking.pk)},
        },
    )
    assert forged.status_code == 400 and "costs 50.00" in forged.content.decode()


def test_the_organizer_sees_revenue_and_attendees_but_cannot_edit_bookings(client_as):
    tier = create(TicketTier, price=Decimal("25.00"), quantity=10)
    attendee = client_as("attendee")
    booking = Booking.objects.get(pk=book(attendee, tier).json()["id"])
    booking.status = "confirmed"
    booking.save(update_fields=["status"])
    organizer = client_as(user=tier.event.organizer)

    dashboard = organizer.get(f"/api/events/{tier.event_id}/dashboard/")
    assert dashboard.json() == {"bookings": 1, "tickets": 2, "capacity": 10, "revenue": "50.00"}
    export = organizer.get(f"/api/events/{tier.event_id}/attendees/")
    assert export["Content-Type"].startswith("text/csv")
    assert attendee.user.email in export.content.decode()

    assert organizer.get(f"/api/bookings/{booking.pk}/").status_code == 200
    edit = organizer.patch(
        f"/api/bookings/{booking.pk}/", json.dumps({"quantity": 1}), content_type="application/json"
    )
    assert edit.status_code == 403
    assert attendee.get(f"/api/events/{tier.event_id}/dashboard/").status_code == 403
