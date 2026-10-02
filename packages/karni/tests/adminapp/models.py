"""Models exercised by every ``tests/admin/`` module.

The contract's prescribed test app, one model (or pair) per behaviour:

* ``KitchenSink`` — one of every derivable field shape (char, slug, email,
  url, text, int, decimal, float, bool, date, datetime, duration, json,
  choices char, FK, M2M, file, image, extra non-pk uuid), with more
  display-worthy fields than the ``list_display`` cap;
* ``Category`` / ``Tag2`` — searchable FK and M2M targets (autocomplete);
* ``Note`` — *standalone* ``SoftDeleteModel`` (integer pk, no timestamps or
  audit users), ``AdminMeta.inline_on`` child of ``KitchenSink`` that stays
  registered itself;
* ``Citation`` — points at the soft-delete ``Note`` (FK widening, alive-only
  autocomplete, hard-delete cascade);
* ``Tuned`` — the full ``AdminMeta`` override surface from the contract
  (including ``read_only`` and ``extra={"list_per_page": 10}``);
* ``Memo`` — standalone soft-delete model whose explicit
  ``AdminMeta.list_filter`` must still get the "deleted" filter prepended;
* ``Ledger`` — every Karni mixin *except* soft delete (the append-only
  composition): no soft-delete admin, filter or actions;
* ``ApiCredential`` — password-named field kept out of displays and forms;
* ``Hidden`` — ``AdminMeta.exclude = True`` skips registration;
* ``Metric`` / ``Reading`` — plain-Django FK target with no searchable
  fields, so the autocomplete second pass must leave the FK alone;
* ``Operator`` / ``Bot`` — ``AbstractBaseUser`` subclasses: skipped by
  default, opted in via ``AdminMeta.register = True``;
* ``Explicit`` — registered explicitly in ``tests/adminapp/admin.py``
  (explicit registration always wins).
"""

from __future__ import annotations

import uuid

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models

from karni.models import AuditedModel, BaseModel, SoftDeleteModel, TimestampedModel, UUIDModel


class Category(BaseModel):
    """Searchable FK target: the second pass makes it an autocomplete."""

    name = models.CharField(max_length=200)

    def __str__(self) -> str:
        return self.name


class Tag2(BaseModel):
    """Searchable M2M target: the second pass makes it an autocomplete."""

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class KitchenSink(BaseModel):
    """The derivation target: one of every interesting field shape.

    Declares more display-worthy fields than the default ``list_display``
    cap (6) so it demonstrably truncates, plus every field type the rules
    must skip: text, duration, json, file, image, M2M and a non-pk UUID.
    """

    class Status(models.TextChoices):
        """A choices char field: filterable, never searchable."""

        DRAFT = "draft", "Draft"
        LIVE = "live", "Live"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    url = models.URLField(blank=True)
    blurb = models.TextField(blank=True)
    count = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    rating = models.FloatField(default=0.0)
    featured = models.BooleanField(default=False)
    published_on = models.DateField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    runtime = models.DurationField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sinks",
    )
    tags = models.ManyToManyField(Tag2, blank=True, related_name="sinks")
    attachment = models.FileField(upload_to="attachments/", blank=True)
    cover = models.ImageField(upload_to="covers/", blank=True)
    token = models.UUIDField(default=uuid.uuid4, editable=False)

    def __str__(self) -> str:
        return self.name


class Note(SoftDeleteModel):
    """Standalone soft-delete subject, inlined on ``KitchenSink`` via ``inline_on``.

    Only the soft-delete mixin: integer pk, ``deleted_at`` and nothing else
    from Karni — the admin must work without timestamps or audit users.
    """

    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    kitchen = models.ForeignKey(
        KitchenSink,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notes",
    )

    class Meta(SoftDeleteModel.Meta):
        ordering = ("title",)

    class AdminMeta:
        """Generate a ``TabularInline`` on the parent; stay registered too."""

        inline_on = "kitchen"

    def __str__(self) -> str:
        return self.title


class Citation(BaseModel):
    """Points at the soft-delete ``Note``.

    Exercises the FK-widening form field (a deleted current value stays
    valid), the alive-only autocomplete endpoint and the hard-delete cascade
    (``CASCADE`` from ``Note``).
    """

    label = models.CharField(max_length=200)
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="citations")

    def __str__(self) -> str:
        return self.label


class Tuned(BaseModel):
    """The contract's ``AdminMeta`` example: every override attribute at once."""

    class Status(models.TextChoices):
        """Payment state — target of the explicit ``list_filter``."""

        DRAFT = "draft", "Draft"
        PAID = "paid", "Paid"

    number = models.CharField(max_length=50)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    issued_at = models.DateTimeField(null=True, blank=True)

    class AdminMeta:
        """Explicit values beating derivation, ``read_only`` extending it."""

        list_display = ["number", "total"]
        list_filter = ["status"]
        search_fields = ["number"]
        read_only = ["total"]
        date_hierarchy = "issued_at"
        ordering = ["-issued_at"]
        extra = {"list_per_page": 10}

    def __str__(self) -> str:
        return self.number


class Memo(SoftDeleteModel):
    """Soft-delete model with an *explicit* ``AdminMeta.list_filter``.

    The derived "deleted" filter must still be prepended so the changelist
    stays alive-by-default.
    """

    class Topic(models.TextChoices):
        """Routing topic — the explicitly declared filter field."""

        OPS = "ops", "Ops"
        ENG = "eng", "Eng"

    subject = models.CharField(max_length=200)
    topic = models.CharField(max_length=20, choices=Topic.choices, default=Topic.OPS)

    class AdminMeta:
        """Explicit filter list without the soft-delete filter."""

        list_filter = ["topic"]

    def __str__(self) -> str:
        return self.subject


class Ledger(UUIDModel, TimestampedModel, AuditedModel):
    """Append-only composition: every Karni mixin except soft delete.

    Its derived admin must not get the soft-delete mixin, filter or actions,
    while the audit fields still stay read-only and out of the displays.
    """

    entry = models.CharField(max_length=200)
    settled = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.entry


class ApiCredential(BaseModel):
    """Carries a password-named field that must never surface anywhere."""

    label = models.CharField(max_length=100)
    api_password = models.CharField(max_length=128, blank=True, default="")

    def __str__(self) -> str:
        return self.label


class Hidden(BaseModel):
    """Opted out of the admin entirely via ``AdminMeta.exclude``.

    Doubles as the ``list_display`` fallback case: nothing but audit fields
    and a ``TextField`` qualifies, so derivation falls back to ``__str__``.
    """

    body = models.TextField(blank=True)

    class AdminMeta:
        """Skip registration for this model only."""

        exclude = True

    def __str__(self) -> str:
        return self.body[:20]


class Metric(models.Model):
    """Plain-Django FK target with no searchable fields.

    Never an autocomplete target, and the no-``BaseModel`` derivation case:
    integer pk, no audit timestamps, no date fields.
    """

    value = models.IntegerField(default=0)

    def __str__(self) -> str:
        return str(self.value)


class Reading(BaseModel):
    """Points at the unsearchable ``Metric``; keeps the default FK widget."""

    metric = models.ForeignKey(Metric, on_delete=models.CASCADE, related_name="readings")
    taken_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"reading {self.pk}"


class Operator(AbstractBaseUser):
    """``AbstractBaseUser`` subclass with no opt-in: autodiscovery skips it."""

    USERNAME_FIELD = "handle"

    handle = models.CharField(max_length=100, unique=True)


class Bot(AbstractBaseUser):
    """``AbstractBaseUser`` subclass opted in via ``AdminMeta.register``.

    Its derived form must still drop the inherited ``password`` field
    (amendment C5).
    """

    USERNAME_FIELD = "name"

    name = models.CharField(max_length=100, unique=True)

    class AdminMeta:
        """Opt this user-ish model into autodiscovery (amendment C5)."""

        register = True


class Explicit(BaseModel):
    """Registered explicitly in ``tests/adminapp/admin.py``.

    Explicit registration always wins: autodiscovery must leave it (and its
    stock, non-Karni admin class) untouched.
    """

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name
