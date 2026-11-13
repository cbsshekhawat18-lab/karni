"""The family events the booking part publishes (when bookings.family_events is on)."""

from karni.events import declare

for moment, describe in (
    ("confirmed", "A booking was confirmed (paid, or by staff)."),
    ("cancelled", "A booking was cancelled."),
):
    declare(
        f"bookings.booking.{moment}",
        version=1,
        fields={
            "booking": "the booking's id",
            "slot": "the slot's id",
            "starts_at": "when the slot starts (ISO 8601)",
        },
        describe=describe,
    )
