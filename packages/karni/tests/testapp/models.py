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

``Part`` and ``Reading`` are integer-keyed whatever ``KARNI_TEST_PK`` says
(no viewsets): legacy ids, sequences, seeding, and a natural key made of
digits (``Part.number``).

The API models (the trio, the slots, the field-role and audit models) inherit
:data:`ApiBase`: ``BaseModel``, or ``BigIntBaseModel`` when the suite runs
with ``KARNI_TEST_PK=bigint`` (CI runs it both ways). The model-layer set
keeps the base it tests.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from karni.models import (
    AuditedModel,
    BaseModel,
    BigIntBaseModel,
    OrderedTreeModel,
    SoftDeleteModel,
    TimestampedModel,
    TreeModel,
    UUIDModel,
)

#: The key type of the API models: ``uuid`` (the default) or ``bigint``.
TEST_PK = os.environ.get("KARNI_TEST_PK", "uuid")
if TEST_PK not in ("uuid", "bigint"):
    raise RuntimeError(f"KARNI_TEST_PK must be uuid or bigint, not {TEST_PK!r}.")

if TYPE_CHECKING:
    ApiBase = BaseModel
else:
    ApiBase = BigIntBaseModel if TEST_PK == "bigint" else BaseModel


class Venue(ApiBase):
    """Relation target with two searchable text fields and no relations."""

    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100)

    class Karni:
        """Imports and exports name a row by its ``name`` (ADR 0002, P6)."""

        natural_key = "name"

    def __str__(self) -> str:
        return self.name


class Tag(ApiBase):
    """Minimal M2M target."""

    name = models.CharField(max_length=100)

    class Karni:
        """Imports and exports name a row by its ``name`` (ADR 0002, P6)."""

        natural_key = "name"

    def __str__(self) -> str:
        return self.name


class Event(ApiBase):
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


# tree models (tests/tree/): an unordered and an ordered tree, and a model pointing at both


class Region(TreeModel, ApiBase):
    """A region tree: siblings in creation order."""

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, blank=True, default="")

    def __str__(self) -> str:
        return self.name


class Category(OrderedTreeModel, ApiBase):
    """A product category tree whose siblings have a position."""

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Product(ApiBase):
    """An FK and an M2M to tree models: both carry x-karni-tree in the schema."""

    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.PROTECT, related_name="products"
    )
    regions = models.ManyToManyField(Region, blank=True, related_name="products")

    def __str__(self) -> str:
        return self.name


class Listing(ApiBase):
    """A row that reaches the trees through a relation: tree:product__category (tests/treescope)."""

    title = models.CharField(max_length=100)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="listings")

    class Karni:
        import_lookup = {"product": "name"}

    def __str__(self) -> str:
        return self.title


# model layer (tests/test_model_layer.py)


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


class Slot(ApiBase):
    """A model whose invariant lives in clean(): the API runs it (karni.api.serializers)."""

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    def clean(self) -> None:
        if self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "ends_at must be after starts_at."})


class LooseSlot(ApiBase):
    """Same rule, but APIMeta.validate = False keeps the API from running clean()."""

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    class APIMeta:
        validate = False

    def clean(self) -> None:
        if self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "ends_at must be after starts_at."})


class Customer(ApiBase):
    """Field-level visibility (tests/api/test_field_roles.py): roles see different fields."""

    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True, default="")
    internal_note = models.TextField(blank=True, default="")
    salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Karni:
        field_roles = {
            "phone": {"read": ["staff", "user"], "write": ["staff"]},
            "internal_note": ["staff"],
            "salary": {"read": ["staff"]},
        }

    def __str__(self) -> str:
        return self.name


class Ticket(ApiBase):
    """Points at ``Customer`` so ``?expand=customer`` is tested under field roles."""

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="tickets")
    subject = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.subject


class Price(ApiBase):
    """Change history (tests/test_audit.py): every field audited, ``note`` recorded redacted."""

    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="EUR")
    note = models.TextField(blank=True, default="")
    api_token = models.CharField(max_length=64, blank=True, default="")

    class Karni:
        audit = True
        sensitive = ["note"]
        field_roles = {"amount": {"read": ["staff"]}}

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"


class Review(SoftDeleteModel):
    """``SoftDeleteModel`` alone: integer pk, ``CASCADE`` child of ``Book``."""

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="reviews")
    stars = models.PositiveSmallIntegerField(default=5)

    class Meta(SoftDeleteModel.Meta):
        ordering = ("id",)

    def __str__(self) -> str:
        return f"{self.stars} stars"


# integer keys whatever KARNI_TEST_PK says (tests/transfer/test_integer_keys.py)


class Part(BigIntBaseModel):
    """An integer key and a natural key made of digits: a part number is never read as an id."""

    number = models.CharField(max_length=20, unique=True)
    label = models.CharField(max_length=100, blank=True, default="")

    class Karni:
        natural_key = "number"

    def __str__(self) -> str:
        return self.number


class Reading(BigIntBaseModel):
    """An integer key and no natural key: rows are named by id only."""

    part = models.ForeignKey(
        Part, null=True, blank=True, on_delete=models.SET_NULL, related_name="readings"
    )
    value = models.IntegerField(default=0)

    def __str__(self) -> str:
        return f"reading {self.pk}"
