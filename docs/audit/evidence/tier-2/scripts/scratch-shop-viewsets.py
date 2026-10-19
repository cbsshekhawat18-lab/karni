"""shop API: BaseViewSet subclasses, auto-routed: `karni make viewset <Model>`."""

from karni.api import Access, Authenticated, BaseViewSet, Public

from shop.models import Event, Venue


class VenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=Authenticated())
    search_fields = ["name", "city"]


class EventViewSet(BaseViewSet):
    model = Event
    access = Access(read=Public(), write=Authenticated())
