"""The visits test part's connection (karni.preferences)."""

from karni import preferences

preferences.connection(
    "visits.visit_events",
    needs=["events"],
    default=True,
    describe="Each logged visit is published as a family event.",
)
