"""The Venue API: CRUD, access."""

from karni.testing import APITestCase

from events.viewsets import VenueViewSet


class VenueAPITests(APITestCase):
    def test_crud(self) -> None:
        self.assert_crud(VenueViewSet)
