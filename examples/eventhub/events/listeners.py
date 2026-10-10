from django.core.mail import send_mail
from django.utils import timezone
from karni.accounts.permissions import assign_role
from karni.events import on_created, on_updated
from karni_payments.models import Payment

from events.models import Booking


@on_created("karni_accounts.User")
def grant_attendee_role(user) -> None:
    """Everyone who signs up can book; organizers and staff are promoted by staff."""
    assign_role(user, "attendee")


@on_updated(Payment)
def confirm_paid_booking(payment: Payment) -> None:
    """The payments webhook moved a payment to succeeded: confirm its booking."""
    if payment.status != Payment.Status.SUCCEEDED:
        return
    for booking in Booking.objects.filter(payment=payment, status=Booking.Status.PENDING):
        booking.status = Booking.Status.CONFIRMED
        booking.confirmed_at = timezone.now()
        booking.save(update_fields=["status", "confirmed_at", "updated_at"])


@on_updated(Booking, queued=True)
def send_booking_confirmation(booking: Booking) -> None:
    """Runs after Booking rows are updated — in a Celery worker, after commit."""
    if booking.status != Booking.Status.CONFIRMED or booking.confirmation_sent_at:
        return
    event = booking.event
    send_mail(
        subject=f"Your tickets for {event.title}",
        message=(
            f"{booking.quantity} x {booking.tier.name} for {event.title} on "
            f"{event.starts_at:%d %b %Y %H:%M} at {event.venue.name}. See you there!"
        ),
        from_email=None,
        recipient_list=[booking.attendee.email],
    )
    Booking.objects.filter(pk=booking.pk).update(confirmation_sent_at=timezone.now())
