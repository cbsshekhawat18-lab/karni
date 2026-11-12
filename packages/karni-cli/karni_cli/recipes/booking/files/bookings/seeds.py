"""bookings demo data for karni seed. Each seeder extends the one karni build writes in
bookings/karni/seeds.py: steer a field's values here.

The resources, prices and times are invented. Replace RESOURCES with your own.
"""

import datetime as dt
from decimal import Decimal
from typing import Any, NamedTuple

from bookings.karni import seeds as karni
from karni.seeding import SeedContext, cycled

from bookings.models import Resource, Slot


class Offer(NamedTuple):
    """A bookable thing: its price per slot, the places in a slot and when slots run."""

    name: str
    description: str
    price: str
    capacity: int
    minutes: int
    starts: tuple[int, ...]  # the hours a slot can start at


RESOURCES = [
    Offer(
        "Meeting Room Cedar",
        "A quiet room for up to eight people with a screen, a whiteboard and daylight.",
        "35.00",
        8,
        60,
        (9, 10, 11, 14, 15, 16),
    ),
    Offer(
        "Workshop Studio",
        "An open floor with long tables and a sink, for classes of twelve.",
        "90.00",
        12,
        180,
        (9, 14),
    ),
    Offer(
        "Podcast Booth",
        "A sound-treated booth with two microphones and a mixer for a host and a "
        "guest.",
        "25.00",
        2,
        90,
        (9, 11, 14, 16),
    ),
    Offer(
        "Garden Courtyard",
        "A covered courtyard with benches and heaters for small gatherings of ten.",
        "60.00",
        10,
        120,
        (12, 15, 18),
    ),
]
NOTES = [
    "Please set the tables in a horseshoe.",
    "We will need the screen and a spare cable.",
    "Two guests arrive early, can they come in at the start?",
    "Bringing our own coffee, no catering needed.",
    "First time here, could someone show us where the entrance is?",
    "Please leave the whiteboard markers out.",
    "We may run a few minutes over and will tidy up quickly.",
]


def _offer(resource: Resource, position: int) -> Offer:
    """The offer a resource row was made from, else the one at its position."""
    for offer in RESOURCES:
        if resource.name.startswith(offer.name):  # also "Meeting Room Cedar 2"
            return offer
    return RESOURCES[position % len(RESOURCES)]


class ResourceSeeder(karni.ResourceSeeder):
    """Rooms and spaces that people book by the slot."""

    def seed(self, context: SeedContext) -> list[Any]:
        names = [offer.name for offer in RESOURCES]
        rows: list[Any] = []
        for number in range(context.count):
            offer = RESOURCES[number % len(RESOURCES)]
            rows += context.create(
                1,
                name=cycled(names, number),
                description=offer.description,
                price=Decimal(offer.price),
            )
        return rows


class SlotSeeder(karni.SlotSeeder):
    """Slots over the coming weeks, in each resource's own hours and length and size."""

    def seed(self, context: SeedContext) -> list[Any]:
        resources = list(Resource.objects.order_by("name"))
        today = context.run.anchor.replace(hour=0, minute=0, second=0, microsecond=0)
        rows: list[Any] = []
        for number in range(context.count):
            if not resources:
                rows += context.create(1)
                continue
            position = number % len(resources)
            offer = _offer(resources[position], position)
            turn = number // len(resources)
            day = today + dt.timedelta(
                days=1 + turn // len(offer.starts) * 2 + position % 2
            )
            start = day.replace(hour=offer.starts[turn % len(offer.starts)])
            rows += context.create(
                1,
                resource=resources[position],
                starts_at=start,
                ends_at=start + dt.timedelta(minutes=offer.minutes),
                capacity=offer.capacity,
            )
        return rows


class BookingSeeder(karni.BookingSeeder):
    """Members' places, spread over the slots that still have room.

    A booking that finds every slot full is made cancelled, so it takes no place.
    """

    def seed(self, context: SeedContext) -> list[Any]:
        rows: list[Any] = []
        for number in range(context.count):
            open_slots = list(
                Slot.objects.filter(remaining__gt=0).order_by("starts_at", "pk")
            )
            note = NOTES[number % len(NOTES)] if number % 3 == 0 else ""
            if open_slots:
                rows += context.create(
                    1, slot=context.random.choice(open_slots), note=note
                )
            else:
                rows += context.create(1, status="cancelled", note=note)
        return rows
