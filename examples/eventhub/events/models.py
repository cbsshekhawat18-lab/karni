"""events models, each on karni.models.BaseModel: `karni make model <Name>`."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from karni.fields import MoneyField, SearchField
from karni.models import BaseModel


class Venue(BaseModel):
    name = models.CharField(max_length=200)
    address = models.TextField()
    city = models.CharField(max_length=100)
    capacity = models.IntegerField()

    def __str__(self) -> str:
        return self.name


class Event(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft"
        PUBLISHED = "published"
        CANCELLED = "cancelled"

    title = models.CharField(max_length=200)
    description = models.TextField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    venue = models.ForeignKey("Venue", on_delete=models.CASCADE)
    cover_image = models.ImageField(upload_to="events/event/", blank=True)
    # ?search= matches through this column's GIN index (karni.fields.SearchField).
    search = SearchField(sources=["title", "description"])

    def __str__(self) -> str:
        return self.title


class TicketTier(BaseModel):
    event = models.ForeignKey("Event", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    # NUMERIC(10,2) in US dollars (karni-payments charges in KARNI_PAYMENTS_CURRENCY, usd),
    # never negative, Decimal only.
    price = MoneyField(currency="USD", max_digits=10, decimal_places=2, min_value=0)
    quantity = models.IntegerField()

    class Karni:
        cascade = {"event": "a tier only exists inside its event; events are soft-deleted"}

    def __str__(self) -> str:
        return self.name

    @property
    def remaining(self) -> int:
        """Seats not held by a pending or confirmed booking."""
        held = self.booking_set.exclude(status=Booking.Status.CANCELLED)
        return self.quantity - (held.aggregate(total=Sum("quantity"))["total"] or 0)


class Booking(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending"
        CONFIRMED = "confirmed"
        CANCELLED = "cancelled"

    event = models.ForeignKey("Event", on_delete=models.CASCADE)
    tier = models.ForeignKey("TicketTier", on_delete=models.CASCADE)
    attendee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    payment = models.ForeignKey(
        "karni_payments.Payment", on_delete=models.SET_NULL, null=True, blank=True
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmation_sent_at = models.DateTimeField(null=True, blank=True)

    class APIMeta:
        read_only = ["status", "payment", "confirmed_at"]
        exclude = ["confirmation_sent_at"]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.tier} for {self.event}"

    @property
    def total(self) -> Decimal:
        return self.tier.price * self.quantity

    def clean(self) -> None:
        """Only published events; the tier must be the event's; never over capacity."""
        if self.event_id and self.event.status != Event.Status.PUBLISHED:
            raise ValidationError({"event": "Only published events can be booked."})
        if self.tier_id and self.event_id and self.tier.event_id != self.event_id:
            raise ValidationError({"tier": "This ticket tier belongs to another event."})
        if self.quantity < 1:
            raise ValidationError({"quantity": "Book at least one ticket."})
        if self.tier_id:
            held = 0
            if self.pk:  # editing: this booking's own seats are not taken by someone else
                held = Booking.objects.filter(pk=self.pk, tier_id=self.tier_id).exclude(
                    status=Booking.Status.CANCELLED
                ).values_list("quantity", flat=True).first() or 0
            if self.quantity > self.tier.remaining + held:
                raise ValidationError(
                    {"quantity": f"Only {self.tier.remaining} seats left in {self.tier.name}."}
                )
