"""What the booking part does when other things are installed (karni.preferences)."""

from karni import preferences

preferences.connection(
    "bookings.family_events",
    needs=["events"],
    default=True,
    describe=(
        "Confirmed and cancelled bookings are published as family events, so "
        "other parts (a timeline, a CRM) can react to them."
    ),
)
