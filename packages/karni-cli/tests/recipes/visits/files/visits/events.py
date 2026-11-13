"""The family events the visits part publishes."""

from karni.events import declare

declare(
    "visits.visit.logged",
    version=1,
    fields={"visit": "the visit's id"},
    describe="A visit was logged.",
)
