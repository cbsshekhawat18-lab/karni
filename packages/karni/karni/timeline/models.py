"""The timeline's tables: one entry per moment, and the records each entry shows on.

A :class:`TimelineEntry` is written once and not edited: what happened
(``kind``), a title in plain text written at the time, an optional body, who
acted, the person it is about and the family event it came from. Its
:class:`TimelineLink` rows name every other record it shows on (an order, a
ticket, an organisation), through a generic reference, so one entry appears
on the person, the order and the deal, and the timeline never holds a foreign
key into a part.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q
from django.utils import timezone

__all__ = ["TimelineEntry", "TimelineLink"]

#: The longest title an entry keeps. A longer one is cut, ending with "...".
TITLE_LENGTH = 300


class TimelineEntry(models.Model):
    """One moment on a person's or a record's timeline.

    ``kind`` is the family event's name (``helpdesk.ticket.closed``) or a
    part's own kind (``crm.note``). ``source`` is the part that wrote it (the
    first word of the kind by default). ``event_id`` is the id of the family
    event it was written from: one event writes one entry per person, so a
    redelivered event writes nothing twice. ``data`` keeps the event's
    declared fields, or what :func:`karni.timeline.record` was given.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    occurred_at = models.DateTimeField(default=timezone.now)
    kind = models.CharField(max_length=200, db_index=True)
    title = models.CharField(max_length=TITLE_LENGTH)
    body = models.TextField(blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    person = models.ForeignKey(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="timeline_entries",
    )
    source = models.CharField(max_length=64, blank=True, default="")
    event_id = models.UUIDField(null=True, blank=True, editable=False)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ("-occurred_at", "-id")
        verbose_name = "timeline entry"
        verbose_name_plural = "timeline entries"
        indexes = [
            models.Index(fields=["person", "-occurred_at", "-id"], name="timeline_person_recent"),
            models.Index(fields=["-occurred_at", "-id"], name="timeline_recent"),
        ]
        constraints = [
            # One entry per event and person, and one per event without a person, so a
            # redelivered event writes nothing twice.
            models.UniqueConstraint(
                fields=["event_id", "person"],
                condition=Q(event_id__isnull=False, person__isnull=False),
                name="timeline_one_entry_per_event_person",
            ),
            models.UniqueConstraint(
                fields=["event_id"],
                condition=Q(event_id__isnull=False, person__isnull=True),
                name="timeline_one_entry_per_event",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.kind}, {self.occurred_at:%Y-%m-%d %H:%M})"


class TimelineLink(models.Model):
    """A record an entry shows on: any model, by content type and id.

    ``object_id`` holds the record's primary key as text (``str(pk)``), so a
    UUID key and an integer key are both kept. A person merge moves these
    rows to the kept person or organisation like every other generic
    reference.
    """

    entry = models.ForeignKey(TimelineEntry, on_delete=models.CASCADE, related_name="links")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.CharField(max_length=64)
    record = GenericForeignKey("content_type", "object_id")

    class Meta:
        verbose_name = "timeline link"
        verbose_name_plural = "timeline links"
        indexes = [
            models.Index(fields=["content_type", "object_id"], name="timeline_link_record"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["entry", "content_type", "object_id"], name="timeline_one_link_per_record"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.content_type.app_label}.{self.content_type.model}:{self.object_id}"

    @property
    def ref(self) -> str:
        """``"app_label.model:id"`` of the linked record."""
        return f"{self.content_type.app_label}.{self.content_type.model}:{self.object_id}"
