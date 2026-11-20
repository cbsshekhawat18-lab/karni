"""The booking part's settings: Settings, Bookings (karni.preferences)."""

from karni import preferences
from pydantic import Field


@preferences.section("bookings", title="Bookings", change="role:bookings-staff")
class BookingPreferences(preferences.Section):
    """When a cancelled booking is refunded."""

    refund_notice_hours: int = Field(
        0,
        ge=0,
        le=720,
        description=(
            "A paid booking cancelled at least this many hours before its slot "
            "starts is refunded. 0 refunds every cancelled paid booking."
        ),
    )
