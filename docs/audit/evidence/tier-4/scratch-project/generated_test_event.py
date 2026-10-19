"""The Event API: CRUD, access and isolation."""

from karni.testing import APITestCase

from events.viewsets import EventViewSet


class EventAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(EventViewSet)

    def test_owners_cannot_reach_each_others_rows(self) -> None:
        self.assert_isolated(EventViewSet)
