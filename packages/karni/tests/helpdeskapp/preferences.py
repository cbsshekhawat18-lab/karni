"""The help desk test part's settings section (karni.preferences)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from karni import preferences


@preferences.section("helpdeskapp", title="Help desk", change="role:desk-lead")
class HelpdeskPreferences(preferences.Section):
    """How the help desk answers."""

    reply_within_hours: int = Field(24, ge=1, le=168, description="Hours to a first reply.")
    greeting: str = Field("Hello", max_length=40, description="The first word of a reply.")
    priority: Literal["low", "normal", "high"] = Field("normal", description="New tickets'.")


preferences.email(
    "helpdeskapp.ticket_closed",
    title="Ticket closed",
    describe="Sent to the requester when a ticket is closed.",
)
