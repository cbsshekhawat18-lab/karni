"""events models, each on karni.models.BaseModel: `karni make model <Name>`."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from karni.capacity import reserve
from karni.fields import CapacityField, StateField
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

    def __str__(self) -> str:
        return self.title


class TicketTier(BaseModel):
    event = models.ForeignKey("Event", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField()
    remaining = CapacityField(total="quantity")  # the database never lets it drop below 0

    def __str__(self) -> str:
        return self.name


class Booking(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending"
        CONFIRMED = "confirmed"
        CANCELLED = "cancelled"

    event = models.ForeignKey("Event", on_delete=models.CASCADE)
    tier = models.ForeignKey("TicketTier", on_delete=models.CASCADE)
    attendee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    status = StateField(
        states=Status,
        transitions={Status.PENDING: [Status.CONFIRMED, Status.CANCELLED],
                     Status.CONFIRMED: [Status.CANCELLED]},
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

    def save(self, *args, **kwargs) -> None:
        with transaction.atomic():  # the seats are taken with the row, or neither is
            if self._state.adding:
                reserve(self.tier, self.quantity)  # sold out: 409 naming what is left
            super().save(*args, **kwargs)

    def clean(self) -> None:
        """Only published events; the tier must be the event's; tickets fixed once booked."""
        if self.event_id and self.event.status != Event.Status.PUBLISHED:
            raise ValidationError({"event": "Only published events can be booked."})
        if self.tier_id and self.event_id and self.tier.event_id != self.event_id:
            raise ValidationError({"tier": "This ticket tier belongs to another event."})
        if self.quantity < 1:
            raise ValidationError({"quantity": "Book at least one ticket."})
        booked = Booking.objects.filter(pk=self.pk).exclude(tier=self.tier_id, quantity=self.quantity)
        if not self._state.adding and booked.exists():
            raise ValidationError({"quantity": "Cancel this booking and book again to change it."})
