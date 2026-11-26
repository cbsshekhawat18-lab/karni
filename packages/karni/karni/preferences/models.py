"""The preferences tables: the project's details, section values and switches.

* :class:`Details`: one row, the business's own details (name, address,
  phone, emails, sender, logo, time zone, language, currency display).
* :class:`SectionValue`: one row per settings section a part registers,
  holding the values someone changed, as JSON its Pydantic model validated.
* :class:`Switch`: one row per connection or email kind someone switched,
  so the declared default holds until then.

Every table is audited (``class Karni: audit = True``): each change leaves a
ChangeLog row with who made it, and the API's ``history/`` lists them.

Override / escape hatch: read and write through :mod:`karni.preferences.services`
(``preferences.value``, ``save_details``, ``save_section``, ``switch``), which
apply the locks of ``KARNI_PREFERENCES_LOCKED``. The models stay plain Django
models for everything else.
"""

from __future__ import annotations

import zoneinfo
from functools import lru_cache
from typing import Any, ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

__all__ = ["CURRENCY_DISPLAYS", "DETAIL_FIELDS", "Details", "SectionValue", "Switch"]

#: How money shows the currency, the values ``Intl.NumberFormat``'s ``currencyDisplay`` takes.
CURRENCY_DISPLAYS: tuple[tuple[str, str], ...] = (
    ("symbol", "Symbol (US$ 5.00, €5.00)"),
    ("narrowSymbol", "Narrow symbol ($5.00)"),
    ("code", "Code (USD 5.00)"),
    ("name", "Name (5.00 US dollars)"),
)
#: The details a part reads with ``preferences.value("details.<field>", default)``.
DETAIL_FIELDS: tuple[str, ...] = (
    "name",
    "legal_name",
    "address",
    "phone",
    "email",
    "tax_number",
    "sender_name",
    "sender_email",
    "reply_to",
    "time_zone",
    "language",
    "currency",
    "currency_display",
    "logo",
)


@lru_cache(maxsize=1)
def _time_zones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones())


def validate_time_zone(value: str) -> None:
    """An IANA time zone name (``Europe/Lisbon``), or blank for the project's ``TIME_ZONE``."""
    if value and value not in _time_zones():
        raise ValidationError(f"{value!r} is not a time zone name such as Europe/Lisbon.")


class Details(models.Model):
    """The business's own details: one row (``id`` 1) for the whole project.

    A blank field reads as the deployment's default (``KARNI_PREFERENCES_DEFAULTS``)
    or Django's (``TIME_ZONE``, ``LANGUAGE_CODE``), so a new project shows sensible
    values before anyone opens Settings. ``sender_name`` and ``sender_email`` are
    the "From" of the project's emails, ``reply_to`` where answers go.
    """

    ONE: ClassVar[int] = 1

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    name = models.CharField(max_length=200, blank=True, default="")
    legal_name = models.CharField(max_length=200, blank=True, default="")
    address = models.TextField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    email = models.EmailField(blank=True, default="", help_text="Where customers write to.")
    tax_number = models.CharField(
        max_length=60, blank=True, default="", help_text="The tax number, on invoices."
    )
    sender_name = models.CharField(
        max_length=200, blank=True, default="", help_text="The name emails come from."
    )
    sender_email = models.EmailField(
        blank=True, default="", help_text="The address emails come from."
    )
    reply_to = models.EmailField(blank=True, default="", help_text="Where answers go.")
    time_zone = models.CharField(
        max_length=64, blank=True, default="", validators=[validate_time_zone]
    )
    language = models.CharField(
        max_length=16,
        blank=True,
        default="",
        validators=[RegexValidator(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$", "A tag such as en.")],
    )
    currency = models.CharField(
        max_length=3,
        blank=True,
        default="",
        validators=[RegexValidator(r"^[A-Z]{3}$", "An ISO 4217 code such as EUR.")],
        help_text="The project's currency (ISO 4217).",
    )
    currency_display = models.CharField(
        max_length=16, choices=CURRENCY_DISPLAYS, default="symbol", blank=True
    )
    logo = models.FileField(
        upload_to="preferences/",
        blank=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "svg", "webp", "gif"])],
    )
    updated_at = models.DateTimeField(default=timezone.now)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )

    class Meta:
        verbose_name = "details"
        verbose_name_plural = "details"
        constraints = [models.CheckConstraint(condition=Q(id=1), name="preferences_one_details")]

    class Karni:
        audit = True

    def __str__(self) -> str:
        return self.name or "Details"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.id = self.ONE
        self.updated_at = timezone.now()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = {*update_fields, "updated_at"}
        super().save(*args, **kwargs)


class SectionValue(models.Model):
    """The changed values of one settings section, validated by its model.

    ``values`` holds only what someone changed: a field left out reads as its
    declared default. ``version`` is the section's version when they were saved.
    """

    section = models.CharField(max_length=64, unique=True)
    values = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(default=timezone.now)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )

    class Meta:
        ordering = ("section",)
        verbose_name = "section values"
        verbose_name_plural = "section values"

    class Karni:
        audit = True

    def __str__(self) -> str:
        return self.section

    def clean(self) -> None:
        from karni.preferences.registry import find_section
        from karni.preferences.services import validate_section_values

        if find_section(self.section) is None:
            raise ValidationError({"section": f"No section {self.section!r} is registered."})
        try:
            validate_section_values(self.section, self.values)
        except Exception as exc:  # noqa: BLE001 - shown on the form
            raise ValidationError({"values": str(exc)}) from None


class Switch(models.Model):
    """A connection or an email kind someone switched on or off.

    Without a row the declared default holds. ``KARNI_PREFERENCES_LOCKED``
    wins over a row.
    """

    class Kind(models.TextChoices):
        CONNECTION = "connection", "Connection"
        EMAIL = "email", "Email"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=200)
    on = models.BooleanField()
    updated_at = models.DateTimeField(default=timezone.now)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )

    class Meta:
        ordering = ("kind", "name")
        verbose_name = "switch"
        verbose_name_plural = "switches"
        constraints = [
            models.UniqueConstraint(fields=["kind", "name"], name="preferences_one_switch")
        ]

    class Karni:
        audit = True

    def __str__(self) -> str:
        return f"{self.name}: {'on' if self.on else 'off'}"
