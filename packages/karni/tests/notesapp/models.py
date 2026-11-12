"""What the subscriber writes: one note per event, and a tally kept with once()."""

from __future__ import annotations

from django.db import models


class Note(models.Model):
    """One note per delivered event (its id is unique, so a redelivery writes nothing)."""

    event_id = models.UUIDField(unique=True)
    ticket = models.CharField(max_length=64)
    person = models.CharField(max_length=64, blank=True, default="")
    request_id = models.CharField(max_length=128, blank=True, default="")

    def __str__(self) -> str:
        return f"note for ticket {self.ticket}"


class Tally(models.Model):
    """How many closures the notes app counted (a counter has no unique key of its own)."""

    name = models.CharField(max_length=50, unique=True)
    count = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.name}: {self.count}"
