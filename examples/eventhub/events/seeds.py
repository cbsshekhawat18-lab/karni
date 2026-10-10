"""events demo data for `karni seed`."""

from datetime import timedelta
from decimal import Decimal

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone
from karni.seeding import SeedContext, Seeder

from events.models import Booking, Event, TicketTier, Venue

# organizer@example.com and attendee@example.com come from KARNI_SEED_LOGINS (.env).


class VenueSeeder(Seeder):
    class Meta:
        model = Venue
        count = 3

    name = factory.Iterator(["Riverside Hall", "The Foundry", "Hilltop Pavilion"])
    city = factory.Iterator(["Jaipur", "Bengaluru", "Pune"])
    capacity = factory.Iterator([400, 150, 900])


class EventSeeder(Seeder):
    class Meta:
        model = Event
        count = 6

    title = factory.Iterator(
        [
            "Open Source Summit",
            "Jazz by the River",
            "Founders Breakfast",
            "Design Systems Day",
            "Marathon Expo",
            "Winter Film Night",
        ]
    )
    status = factory.Iterator(["published"] * 5 + ["draft"])
    cover_image = ""
    organizer = factory.LazyFunction(
        lambda: get_user_model().objects.get(email="organizer@example.com")
    )
    starts_at = factory.Sequence(lambda n: timezone.now() + timedelta(days=7 + 4 * n, hours=10))
    ends_at = factory.LazyAttribute(lambda event: event.starts_at + timedelta(hours=3))


class TicketTierSeeder(Seeder):
    class Meta:
        model = TicketTier

    def seed(self, context: SeedContext) -> list:
        tiers = (("General", Decimal("25.00"), 100), ("VIP", Decimal("90.00"), 20))
        return [
            context.create(1, event=event, name=name, price=price, quantity=quantity)[0]
            for event in Event.objects.order_by("starts_at")
            for name, price, quantity in tiers
        ]


class BookingSeeder(Seeder):
    class Meta:
        model = Booking

    def seed(self, context: SeedContext) -> list:
        attendee = get_user_model().objects.get(email="attendee@example.com")
        rows = []
        tiers = TicketTier.objects.filter(event__status="published")
        for index, tier in enumerate(tiers.order_by("event__starts_at", "price")):
            confirmed = index % 3 != 2
            rows += context.create(
                1,
                event=tier.event,
                tier=tier,
                attendee=attendee,
                quantity=1 + index % 3,
                status="confirmed" if confirmed else "pending",
                confirmed_at=timezone.now() if confirmed else None,
                confirmation_sent_at=timezone.now() if confirmed else None,
            )
        return rows
