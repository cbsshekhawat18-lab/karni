"""The TicketTier API: CRUD, access and isolation."""

from karni.testing import APITestCase

from events.viewsets import TicketTierViewSet


class TicketTierAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(TicketTierViewSet)

    def test_organizers_cannot_reach_each_others_draft_tiers(self) -> None:
        # Tiers of published events are public by design; drafts are not.
        self.assert_isolated(TicketTierViewSet, "organizer", values={"event__status": "draft"})
