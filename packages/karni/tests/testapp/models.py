"""Models exercised by every ``tests/api/`` module.

The trio covers the shapes the api contract cares about: plain fields of every
derivable filter type, choices, nullable numerics, forward FKs (one to the
user model), an M2M, and an ``APIMeta`` with both ``read_only`` and
``write_only`` entries (``Event``); relation targets with no relations of
their own (``Venue``, ``Tag``).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from karni.models import BaseModel


class Venue(BaseModel):
    """Relation target with two searchable text fields and no relations."""

    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Tag(BaseModel):
    """Minimal M2M target."""

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Event(BaseModel):
    """The contract's target model: one of every interesting field shape."""

    class Status(models.TextChoices):
        """Publication state — kept to two values for the schema enum tests."""

        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    capacity = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    is_public = models.BooleanField(default=True)
    internal_note = models.CharField(max_length=200, blank=True, default="")
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    venue = models.ForeignKey(
        Venue,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="events")

    class APIMeta:
        """``status`` is server-controlled; ``internal_note`` is write-only."""

        read_only = ["status"]
        write_only = ["internal_note"]

    def __str__(self) -> str:
        return self.title
