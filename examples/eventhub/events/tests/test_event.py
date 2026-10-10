"""The Event API: CRUD, access and isolation."""

from karni.testing import APITestCase

from events.viewsets import EventViewSet


class EventAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(EventViewSet)

    def test_organizers_cannot_reach_each_others_drafts(self) -> None:
        # Published events are public by design; drafts are the organizer's own.
        self.assert_isolated(EventViewSet, "organizer", values={"status": "draft"})
