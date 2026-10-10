"""The Booking API: CRUD, access and isolation."""

from karni.testing import APITestCase
from karni.testing.factories import create

from events.models import TicketTier
from events.viewsets import BookingViewSet


class BookingAPITests(APITestCase):
    def test_crud(self) -> None:
        # Rows and payloads must respect the capacity rule: one tier, one seat each.
        tier = create(TicketTier, quantity=50)
        self.assert_crud(
            BookingViewSet,
            values={"event": tier.event, "tier": tier, "quantity": 1},
            payload={"event": str(tier.event_id), "tier": str(tier.pk), "quantity": 1},
        )

    def test_owners_cannot_reach_each_others_rows(self) -> None:
        self.assert_isolated(BookingViewSet)
