"""Models exercised by every ``tests/api/`` module, plus the model-layer set.

The trio covers the shapes the api contract cares about: plain fields of every
derivable filter type, choices, nullable numerics, forward FKs (one to the
user model), an M2M, and an ``APIMeta`` with both ``read_only`` and
``write_only`` entries (``Event``); relation targets with no relations of
their own (``Venue``, ``Tag``).

The second group backs ``tests/test_model_layer.py`` (no viewsets, so the API
and its schema never see them; they live in an installed app because cascades
and admin need real reverse relations):

* ``Stamp`` / ``Entry`` / ``Remark`` — ``UUIDModel``, ``TimestampedModel`` and
  ``AuditedModel`` each used *alone*;
* ``Shelf`` → ``Book`` ↔ ``Label`` — ``BaseModel`` parent/child (``CASCADE``)
  and M2M, every primary key a UUID;
* ``Review`` — ``SoftDeleteModel`` used alone (integer pk) as a ``CASCADE``
  child of the UUID-keyed ``Book``.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from karni.models import AuditedModel, BaseModel, SoftDeleteModel, TimestampedModel, UUIDModel


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

    class Karni:
        """Roles-as-data metadata (tests/accounts/test_roles.py): owned by the organizer."""

        owner_field = "organizer"
        scope_paths = {"venue": "venue"}
        actions = ["approve"]

    def __str__(self) -> str:
        return self.title


# --- model layer (tests/test_model_layer.py) ---------------------------------


class Stamp(UUIDModel):
    """``UUIDModel`` alone: a UUID primary key and nothing else from Karni."""

    value = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.value


class Entry(TimestampedModel):
    """``TimestampedModel`` alone: integer pk, ``created_at`` / ``updated_at``."""

    text = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.text


class Remark(AuditedModel):
    """``AuditedModel`` alone: integer pk, ``created_by`` / ``updated_by``."""

    text = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.text


class Shelf(BaseModel):
    """``BaseModel`` parent of ``Book``."""

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Label(BaseModel):
    """``BaseModel`` M2M target of ``Book``."""

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Book(BaseModel):
    """``BaseModel`` child: FK and M2M, both to UUID-keyed models."""

    shelf = models.ForeignKey(Shelf, on_delete=models.CASCADE, related_name="books")
    title = models.CharField(max_length=100)
    labels = models.ManyToManyField(Label, blank=True, related_name="books")

    def __str__(self) -> str:
        return self.title


class Slot(BaseModel):
    """A model whose invariant lives in clean(): the API runs it (karni.api.serializers)."""

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    def clean(self) -> None:
        if self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "ends_at must be after starts_at."})


class LooseSlot(BaseModel):
    """Same rule, but APIMeta.validate = False keeps the API from running clean()."""

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    class APIMeta:
        validate = False

    def clean(self) -> None:
        if self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "ends_at must be after starts_at."})


class Review(SoftDeleteModel):
    """``SoftDeleteModel`` alone: integer pk, ``CASCADE`` child of ``Book``."""

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="reviews")
    stars = models.PositiveSmallIntegerField(default=5)

    class Meta(SoftDeleteModel.Meta):
        ordering = ("id",)

    def __str__(self) -> str:
        return f"{self.stars} stars"
