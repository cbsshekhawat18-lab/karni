from django.core.mail import send_mail
from django.utils import timezone
from karni.capacity import release, reserve
from karni.events import on_deleted, on_restored, on_transition, on_updated
from karni_payments.models import Payment

from events.models import Booking


@on_updated(Payment)
def confirm_paid_booking(payment: Payment) -> None:
    """The payments webhook moved a payment to succeeded: confirm its booking."""
    if payment.status != Payment.Status.SUCCEEDED:
        return
    for booking in Booking.objects.filter(payment=payment, status=Booking.Status.PENDING):
        booking.transition("status", Booking.Status.CONFIRMED, confirmed_at=timezone.now())


@on_transition(Booking, "status", to=Booking.Status.CANCELLED)
def release_seats(booking: Booking) -> None:
    """A cancelled booking gives its seats back, in the cancelling transaction."""
    release(booking.tier, booking.quantity)


@on_deleted(Booking)
def release_deleted_seats(booking: Booking) -> None:
    if booking.status != Booking.Status.CANCELLED:  # a cancelled one already gave them back
        release(booking.tier, booking.quantity)


@on_restored(Booking)
def retake_restored_seats(booking: Booking) -> None:
    """A restored booking takes its seats again; sold out refuses the restore (E985)."""
    if booking.status != Booking.Status.CANCELLED:
        reserve(booking.tier, booking.quantity)


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
