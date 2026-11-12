"""Experimental. The people contract's tables: Person, Organisation, Membership, Address.

A :class:`Person` is the one record of a human the business deals with, in
every part of a project: a shop's buyer, a CRM contact, a booking guest and a
student are the same row when their email is the same. A person may have a
user account (``user``) or none (a guest, a lead, an imported contact). An
:class:`Organisation` is the one record of a company. A part extends them
with a table of its own (a profile one-to-one with Person, or rows that point
at a person), never with columns.

Rules the rows keep, in the database and in ``clean()`` (the API and the
admin run it):

* ``Person.email`` is stored lower case and is unique among live people when
  it is not blank (``E254``). A person linked to an account keeps the
  account's email: change it through the account (``E255``).
* An address belongs to a person or an organisation, never both and never
  neither (``E256``). Each owner has at most one default billing and one
  default shipping address: saving a default clears the owner's other one.
* A person is a member of an organisation once (live rows).

Override / escape hatch: the services in :mod:`karni.people.services` are
the way to create, merge and erase people (``people.resolve``,
``people.merge``, ``people.erase``); the models stay plain Django models
for everything else.
"""

from __future__ import annotations

import re
import zoneinfo
from functools import lru_cache
from typing import Any, ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q

from karni.fields import CountryField, LiveUniqueConstraint
from karni.managers import BaseQuerySet, ScopedManagerMixin
from karni.models import BaseModel

__all__ = [
    "Address",
    "Membership",
    "Organisation",
    "Person",
    "PersonManager",
    "PersonQuerySet",
    "normalize_domain",
    "normalize_email",
]

#: ``language``: a BCP 47 tag such as ``en``, ``pt-BR`` or ``zh-Hant``.
_LANGUAGE = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")
#: What ``display_name`` falls back to when a person has neither a name nor an email.
UNNAMED = "Unnamed person"
#: What an erased person is called.
ERASED = "Erased person"


def normalize_email(value: Any) -> str:
    """Experimental. ``value`` stripped and lower case: the form ``Person.email`` is kept in."""
    return str(value or "").strip().lower()


def normalize_domain(value: Any) -> str:
    """Experimental. A domain without scheme, path, ``www.`` or a trailing dot, lower case."""
    text = str(value or "").strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    text = text.split("/", 1)[0].split("?", 1)[0].rstrip(".")
    return text.removeprefix("www.")


@lru_cache(maxsize=1)
def _time_zones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones())


def _refuse(field: str, message: str, code: str) -> ValidationError:
    return ValidationError({field: [f"{message} ({code})"]}, code=code)


class PersonQuerySet(BaseQuerySet):
    """Experimental. ``Person.objects``'s queryset: soft delete aware, with the person facts."""

    def with_facts(self, *names: str) -> PersonQuerySet:
        """Annotate the person facts ``names`` (none: every registered fact).

        Each fact is one SQL expression (a correlated subquery), so a filter
        or an ordering on it runs in the database:
        ``Person.objects.with_facts("orders").filter(orders__gte=3)``.
        """
        from karni.people.registry import annotate_facts

        return annotate_facts(self, names or None)  # type: ignore[return-value]


class PersonManager(ScopedManagerMixin, models.Manager.from_queryset(PersonQuerySet)):  # type: ignore[misc]
    """Experimental. ``Person.objects``: :class:`karni.managers.BaseManager` with ``with_facts``."""


class Organisation(BaseModel):
    """Experimental. A company, a school, a club: one row per organisation, in every part.

    ``domain`` is kept lower case without scheme or ``www.``. ``merged_into``
    points at the organisation this one was merged into (``people.merge``).
    """

    name = models.CharField(max_length=200)
    domain = models.CharField(
        max_length=253, blank=True, default="", help_text="The web domain, e.g. example.com."
    )
    phone = models.CharField(max_length=40, blank=True, default="")
    source = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="The part that created it: an app label such as shop or crm.",
    )
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, editable=False, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(BaseModel.Meta):
        verbose_name = "organisation"
        verbose_name_plural = "organisations"
        ordering = ("name",)
        indexes = [models.Index(fields=["domain"], name="people_org_domain_idx")]

    class Karni:
        audit = True
        actions: ClassVar[list[str]] = ["merge"]
        explicit_actions: ClassVar[list[str]] = ["merge"]
        search: ClassVar[dict[str, Any]] = {
            "fields": ["name", "domain"],
            "title": "name",
            "subtitle": "domain",
        }

    class APIMeta:
        read_only: ClassVar[list[str]] = ["merged_into", "source"]

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["name", "domain", "phone", "source"]
        search_fields: ClassVar[list[str]] = ["name", "domain"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.domain = normalize_domain(self.domain)
        super().save(*args, **kwargs)


class Person(BaseModel):
    """Experimental. A human the business deals with: one row per person, in every part.

    ``display_name`` is what every screen shows. Left blank, or still the
    name the given and family names made, it follows them; written by hand,
    it stays. ``user`` is the person's account, linked only once its email is
    verified (:func:`karni.people.link_account`). ``source`` is the part that
    created the row. ``merged_into`` and ``erased_at`` record what
    ``people.merge`` and ``people.erase`` did; both rows end soft-deleted.
    """

    given_name = models.CharField(max_length=150, blank=True, default="")
    family_name = models.CharField(max_length=150, blank=True, default="")
    display_name = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text="What screens show. Blank: the full name, else the email.",
    )
    email = models.EmailField(max_length=254, blank=True, default="")
    phone = models.CharField(max_length=40, blank=True, default="")
    organisation = models.ForeignKey(
        Organisation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="primary_people",
        help_text="The organisation the person mainly belongs to.",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="person",
        help_text="The person's account, linked once its email is verified.",
    )
    time_zone = models.CharField(
        max_length=64, blank=True, default="", help_text="An IANA time zone, e.g. Europe/Paris."
    )
    language = models.CharField(
        max_length=16, blank=True, default="", help_text="A language tag, e.g. en or pt-BR."
    )
    source = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="The part that created it: an app label such as shop or crm.",
    )
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, editable=False, on_delete=models.SET_NULL, related_name="+"
    )
    erased_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects: ClassVar[PersonManager] = PersonManager()

    class Meta(BaseModel.Meta):
        verbose_name = "person"
        verbose_name_plural = "people"
        ordering = ("display_name", "email")
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(
                fields=["email"], condition=~Q(email=""), name="people_person_email_live_uniq"
            )
        ]
        indexes: ClassVar[list[Any]] = [
            models.Index(fields=["display_name"], name="people_person_display_idx")
        ]

    class Karni:
        audit = True
        owner_field = "user"
        actions: ClassVar[list[str]] = ["merge", "erase"]
        explicit_actions: ClassVar[list[str]] = ["merge", "erase"]
        search: ClassVar[dict[str, Any]] = {
            "fields": ["display_name", "email", "phone"],
            "title": "display_name",
            "subtitle": "email",
        }

    class APIMeta:
        read_only: ClassVar[list[str]] = ["user", "merged_into", "erased_at", "source"]

    class AdminMeta:
        list_display: ClassVar[list[str]] = ["display_name", "email", "phone", "organisation"]
        search_fields: ClassVar[list[str]] = ["display_name", "email", "phone"]

    def __str__(self) -> str:
        return self.display_name or self.email or UNNAMED

    @classmethod
    def from_db(cls, db: str | None, field_names: Any, values: Any) -> Any:
        instance = super().from_db(db, field_names, values)
        instance._karni_loaded = {
            name: instance.__dict__.get(name)
            for name in ("given_name", "family_name", "email", "display_name")
        }
        return instance

    def full_name(self) -> str:
        """The given and family names, joined with a space (``""`` when both are blank)."""
        return " ".join(
            part for part in (self.given_name.strip(), self.family_name.strip()) if part
        )

    def default_display_name(self) -> str:
        """The name a blank ``display_name`` takes: the full name, else the email's local part."""
        return self.full_name() or self.email.split("@", 1)[0] or UNNAMED

    def _display_follows_names(self) -> bool:
        loaded = getattr(self, "_karni_loaded", None)
        if not self.display_name.strip():
            return True
        if loaded is None:
            return False
        before = Person(
            given_name=loaded.get("given_name") or "",
            family_name=loaded.get("family_name") or "",
            email=loaded.get("email") or "",
        )
        return self.display_name == before.default_display_name()

    def clean(self) -> None:
        """The person's rules as form errors: the email, the time zone and the language."""
        super().clean()
        self.email = normalize_email(self.email)
        if self.email:
            taken = Person.objects.filter(email=self.email).exclude(pk=self.pk)
            if taken.exists():
                raise _refuse(
                    "email",
                    f"Another person already has the email {self.email}. One email is one "
                    "person: open that person instead, or merge the two.",
                    "E254",
                )
        if self.user_id is not None and self.pk is not None:  # type: ignore[attr-defined]
            stored = Person._base_manager.filter(pk=self.pk).values_list("email", flat=True).first()
            if stored is not None and stored != self.email:
                raise _refuse(
                    "email",
                    "This person has an account, and the account's verified email is the "
                    "person's email. Change the email through the account.",
                    "E255",
                )
        if self.time_zone and self.time_zone not in _time_zones():
            raise _refuse(
                "time_zone",
                f"{self.time_zone!r} is not an IANA time zone. Use a name such as Europe/Paris "
                "or America/New_York.",
                "E256",
            )
        if self.language and not _LANGUAGE.fullmatch(self.language):
            raise _refuse(
                "language",
                f"{self.language!r} is not a language tag. Use one such as en, fr or pt-BR.",
                "E256",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = normalize_email(self.email)
        update_fields = kwargs.get("update_fields")
        if self._display_follows_names() and self.erased_at is None:
            self.display_name = self.default_display_name()[:300]
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "display_name"}
        super().save(*args, **kwargs)
        self._karni_loaded = {
            name: getattr(self, name)
            for name in ("given_name", "family_name", "email", "display_name")
        }

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Soft-delete the person. A deleted person holds no account: ``user`` is cleared first.

        The account can then be linked to another person (one account, one
        person). Restoring the row does not link it again.
        """
        with transaction.atomic(using=using or self._state.db):
            if self.user_id is not None:  # type: ignore[attr-defined]
                self.user = None
                self.save(using=using, update_fields=["user"])
            return super().delete(using=using, keep_parents=keep_parents)

    delete.alters_data = True  # type: ignore[attr-defined]


class Membership(BaseModel):
    """Experimental. A person belongs to an organisation, with a title (``Head of sales``)."""

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="memberships")
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="memberships"
    )
    title = models.CharField(max_length=200, blank=True, default="")

    class Meta(BaseModel.Meta):
        verbose_name = "membership"
        verbose_name_plural = "memberships"
        ordering = ("organisation__name", "person__display_name")
        constraints: ClassVar[list[Any]] = [
            LiveUniqueConstraint(
                fields=["person", "organisation"], name="people_membership_live_uniq"
            )
        ]

    class Karni:
        audit = True
        owner_field = "person__user"

    def __str__(self) -> str:
        title = f", {self.title}" if self.title else ""
        return f"{self.person} at {self.organisation}{title}"

    def clean(self) -> None:
        super().clean()
        if self.person_id is None or self.organisation_id is None:  # type: ignore[attr-defined]
            return
        taken = Membership.objects.filter(
            person_id=self.person_id,  # type: ignore[attr-defined]
            organisation_id=self.organisation_id,  # type: ignore[attr-defined]
        ).exclude(pk=self.pk)
        if taken.exists():
            raise _refuse(
                "organisation",
                "This person is already a member of this organisation. Change that membership's "
                "title instead.",
                "E256",
            )


class Address(BaseModel):
    """Experimental. A postal address of a person or of an organisation.

    Exactly one of ``person`` and ``organisation`` is set (a CHECK in the
    database). ``is_default_billing`` and ``is_default_shipping`` mark the
    owner's default for each use: saving a default clears the owner's other
    default of that kind, in the same transaction.
    """

    person = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.CASCADE, related_name="addresses"
    )
    organisation = models.ForeignKey(
        Organisation, null=True, blank=True, on_delete=models.CASCADE, related_name="addresses"
    )
    label = models.CharField(
        max_length=100, blank=True, default="", help_text="A name for it, e.g. Home or Office."
    )
    line1 = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True, default="")
    city = models.CharField(max_length=120, blank=True, default="")
    region = models.CharField(max_length=120, blank=True, default="")
    postcode = models.CharField(max_length=20, blank=True, default="")
    country = CountryField(blank=True, default="")
    is_default_billing = models.BooleanField(default=False)
    is_default_shipping = models.BooleanField(default=False)

    #: The flags of which an owner has one at most.
    DEFAULT_FLAGS: ClassVar[tuple[str, ...]] = ("is_default_billing", "is_default_shipping")

    class Meta(BaseModel.Meta):
        verbose_name = "address"
        verbose_name_plural = "addresses"
        ordering = ("-is_default_shipping", "-is_default_billing", "label", "created_at")
        constraints: ClassVar[list[Any]] = [
            models.CheckConstraint(
                condition=(Q(person__isnull=False) & Q(organisation__isnull=True))
                | (Q(person__isnull=True) & Q(organisation__isnull=False)),
                name="people_address_one_owner",
            ),
            *[
                LiveUniqueConstraint(
                    fields=[owner],
                    condition=Q(**{flag: True}),
                    name=f"people_address_{owner[:3]}_{flag.split('_')[-1]}_uniq",
                )
                for owner in ("person", "organisation")
                for flag in ("is_default_billing", "is_default_shipping")
            ],
        ]

    class Karni:
        audit = True
        owner_field = "person__user"

    def __str__(self) -> str:
        parts = [self.line1, self.city, self.country]
        return ", ".join(part for part in parts if part)

    def owner_filter(self) -> dict[str, Any]:
        """The owner as a filter: ``{"person_id": ...}`` or ``{"organisation_id": ...}``."""
        if self.person_id is not None:  # type: ignore[attr-defined]
            return {"person_id": self.person_id}  # type: ignore[attr-defined]
        return {"organisation_id": self.organisation_id}  # type: ignore[attr-defined]

    def clean(self) -> None:
        super().clean()
        has_person = self.person_id is not None  # type: ignore[attr-defined]
        has_organisation = self.organisation_id is not None  # type: ignore[attr-defined]
        if has_person == has_organisation:
            raise _refuse(
                "person",
                "An address belongs to a person or to an organisation: set exactly one of "
                "person and organisation.",
                "E256",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        flags = [flag for flag in self.DEFAULT_FLAGS if getattr(self, flag)]
        owner = self.owner_filter()
        if not flags or next(iter(owner.values())) is None:
            super().save(*args, **kwargs)
            return
        with transaction.atomic(using=kwargs.get("using") or self._state.db):
            for flag in flags:
                others = Address.objects.filter(**owner, **{flag: True}).exclude(pk=self.pk)
                for other in others:
                    setattr(other, flag, False)
                    other.save(update_fields=[flag])
            super().save(*args, **kwargs)
