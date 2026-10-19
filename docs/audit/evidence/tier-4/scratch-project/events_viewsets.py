"""events API: BaseViewSet subclasses, auto-routed: `karni make viewset <Model>`."""

from karni.api import Access, Authenticated, BaseViewSet, Can, Owned, Public

from events.models import Booking, Event, Venue


class VenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Public(), write=Authenticated())


class EventViewSet(BaseViewSet):
    model = Event
    access = Access(read=Owned("organizer"), write=Owned("organizer"))


class BookingViewSet(BaseViewSet):
    model = Booking
    access = Access(read=Owned("attendee"), write=Owned("attendee"))


# ---- audit4 (Tier 4 audit) — deliberately broken viewsets, registered explicitly in config/api.py


class SlowBookingViewSet(BaseViewSet):
    """A hand viewset that bypasses the optimiser (optimize = False): the N+1 control."""

    model = Booking
    access = Access(read=Owned("attendee"), write=Owned("attendee"))
    auto_register = False
    optimize = False


class LeakyEventViewSet(BaseViewSet):
    """Owned() on paper, but filter_queryset_for_user replaces the scoped queryset: a leak."""

    model = Event
    access = Access(read=Owned("organizer"), write=Owned("organizer"))
    auto_register = False

    # karni: allow(access-override): audit4 — deliberately leaky, to show assert_isolated failing
    def filter_queryset_for_user(self, queryset):
        return Event.objects.all()


class CanVenueViewSet(BaseViewSet):
    """Can(...) as the access predicate (roles as data)."""

    model = Venue
    access = Access(read=Can("events.venue:view"), write=Can("events.venue:change"))
    auto_register = False
