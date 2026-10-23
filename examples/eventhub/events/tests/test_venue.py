"""The Venue API: CRUD, access."""

from karni.testing import APITestCase

from events.viewsets import VenueViewSet


class VenueAPITests(APITestCase):
    def test_crud(self) -> None:
        # Organizers write venues (write=HasRole("organizer", "staff")).
        self.assert_crud(VenueViewSet, "organizer")

    def test_attendees_only_read(self) -> None:
        self.assert_crud(
            VenueViewSet, "attendee", expect={"create": 403, "update": 403, "destroy": 403}
        )
