"""events test factories: declare only what differs."""

import factory
from karni.testing.factories import ModelFactory

from events.models import Booking, Event


class EventFactory(ModelFactory):
    """Test rows for Event; undeclared fields keep their generated values."""

    class Meta:
        model = Event

    # Bookings need a published event (events.serializers); tests get one by default.
    status = "published"

    # Declare only the fields to change, e.g.:
    # title = factory.Faker("catch_phrase")


class BookingFactory(ModelFactory):
    """Test rows for Booking; undeclared fields keep their generated values."""

    class Meta:
        model = Booking

    # A booking's event is its tier's event (events.serializers checks it).
    event = factory.LazyAttribute(lambda booking: booking.tier.event)
    quantity = 1  # each booking reserves seats from its tier (karni.capacity)

    # Declare only the fields to change, e.g.:
    # title = factory.Faker("catch_phrase")
