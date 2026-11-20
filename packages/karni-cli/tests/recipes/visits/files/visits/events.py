"""The family events the visits part publishes."""

from karni.events import declare

declare(
    "visits.visit.logged",
    version=1,
    fields={"visit": "the visit's id", "note": "the visit's note"},
    person="person",
    timeline="Visit logged: {note}",
    describe="A visit was logged.",
)
