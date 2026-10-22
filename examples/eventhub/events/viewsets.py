"""events API: BaseViewSet subclasses, auto-routed: `karni make viewset <Model>`."""

import csv

from django.conf import settings
from django.db.models import DecimalField, F, Q, Sum
from django.http import HttpResponse
from karni.api import Access, Authenticated, BaseViewSet, HasRole, Owned, Public, Where
from karni_payments.services import create_checkout
from rest_framework.decorators import action
from rest_framework.response import Response

from events.models import Booking, Event, TicketTier, Venue

STAFF = HasRole("staff")
PUBLISHED = Where(lambda request: Q(status=Event.Status.PUBLISHED))
TIER_PUBLISHED = Where(lambda request: Q(event__status=Event.Status.PUBLISHED))


class VenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=HasRole("organizer", "staff"))
    search_fields = ("name", "city")


class EventViewSet(BaseViewSet):
    model = Event
    access = Access(
        read=PUBLISHED | Owned("organizer") | STAFF,
        write=Owned("organizer") | STAFF,
        create=HasRole("organizer", "staff"),
    )
    search_fields = ("title", "description")

    @action(detail=True, access=Owned("organizer") | STAFF)
    def dashboard(self, request, pk=None):
        """Bookings, tickets sold and revenue for one event (organizer dashboard)."""
        event = self.get_object()
        confirmed = event.booking_set.filter(status=Booking.Status.CONFIRMED)
        totals = confirmed.aggregate(
            tickets=Sum("quantity"),
            revenue=Sum(F("quantity") * F("tier__price"), output_field=DecimalField()),
        )
        capacity = event.tickettier_set.aggregate(total=Sum("quantity"))["total"] or 0
        return Response(
            {
                "bookings": confirmed.count(),
                "tickets": totals["tickets"] or 0,
                "capacity": capacity,
                "revenue": f"{totals['revenue'] or 0:.2f}",
            }
        )

    @action(detail=True, access=Owned("organizer") | STAFF)
    def attendees(self, request, pk=None):
        """The confirmed attendee list as CSV (organizer export)."""
        event = self.get_object()
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{event.pk}-attendees.csv"'
        writer = csv.writer(response)
        writer.writerow(["email", "tier", "quantity", "booked_at"])
        bookings = event.booking_set.filter(status=Booking.Status.CONFIRMED)
        for booking in bookings.select_related("attendee", "tier").order_by("created_at"):
            writer.writerow(
                [booking.attendee.email, booking.tier.name, booking.quantity, booking.created_at]
            )
        return response


class TicketTierViewSet(BaseViewSet):
    model = TicketTier
    access = Access(
        read=TIER_PUBLISHED | Owned("event__organizer") | STAFF,
        write=Owned("event__organizer") | STAFF,
    )


class BookingViewSet(BaseViewSet):
    model = Booking
    access = Access(
        read=Owned("attendee") | Owned("event__organizer") | STAFF,
        write=Owned("attendee"),
        create=Authenticated(),
    )

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """Open a checkout for this booking; the webhook confirms it when paid."""
        booking = self.get_object()
        back = f"{settings.KARNI_FRONTEND_URL}/bookings/{booking.pk}"
        payment, session = create_checkout(
            request.user,
            amount=booking.total,
            success_url=f"{back}?paid=1",
            cancel_url=back,
            metadata={"booking": str(booking.pk)},
        )
        booking.payment = payment
        booking.save(update_fields=["payment", "updated_at"])
        return Response({"url": session.url, "payment": str(payment.pk)})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        booking.transition("status", Booking.Status.CANCELLED)  # releases the seats
        return Response(self.get_serializer(booking).data)
