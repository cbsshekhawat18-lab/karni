"""The Venue API: CRUD, access, response caching."""

from karni.testing import APITestCase

from events.models import Venue
from events.viewsets import VenueViewSet


class VenueAPITests(APITestCase):
    def test_crud(self) -> None:
        # Organizers write venues (write=HasRole("organizer", "staff")).
        self.assert_crud(VenueViewSet, "organizer")

    def test_attendees_only_read(self) -> None:
        self.assert_crud(
            VenueViewSet, "attendee", expect={"create": 403, "update": 403, "destroy": 403}
        )

    def test_responses_are_cached_until_a_venue_changes(self) -> None:
        Venue.objects.create(name="Hall", address="1 Main St", city="Lyon", capacity=100)
        visitor = self.client_as(None)
        assert visitor.get("/api/venues/")["X-Cache"] == "MISS"
        cached = visitor.get("/api/venues/")
        assert cached["X-Cache"] == "HIT"
        venue_id = cached.json()["results"][0]["id"]
        organizer = self.client_as("organizer")
        assert organizer.patch(f"/api/venues/{venue_id}/", {"name": "Arena"}).status_code == 200
        fresh = visitor.get("/api/venues/")
        assert fresh["X-Cache"] == "MISS" and fresh.json()["results"][0]["name"] == "Arena"
