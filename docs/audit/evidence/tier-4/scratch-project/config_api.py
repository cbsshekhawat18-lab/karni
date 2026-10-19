"""audit4: explicit router factory (the documented KARNI_API_ROUTER escape hatch).

Autodiscovery runs first so the generated viewsets stay "the viewset that
serves the model" (relation scoping, x-karni-relation: first registered
wins); the audit's deliberately-broken viewsets are then registered under
their own prefixes and basenames.
"""

from karni.api.routers import KarniRouter


def get_router() -> KarniRouter:
    from events.viewsets import CanVenueViewSet, LeakyEventViewSet, SlowBookingViewSet

    router = KarniRouter()
    router.autodiscover()
    router.register("slow-bookings", SlowBookingViewSet, basename="events-slow-booking")
    router.register("leaky-events", LeakyEventViewSet, basename="events-leaky-event")
    router.register("can-venues", CanVenueViewSet, basename="events-can-venue")
    return router
