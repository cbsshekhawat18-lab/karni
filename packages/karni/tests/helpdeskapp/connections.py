"""The help desk test part's connections (karni.preferences)."""

from __future__ import annotations

from karni import preferences

preferences.connection(
    "helpdeskapp.ticket_timeline",
    needs=["timeline"],
    default=True,
    describe="A closed ticket is written on the requester's timeline.",
)
