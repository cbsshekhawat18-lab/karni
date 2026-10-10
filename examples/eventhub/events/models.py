"""events models, each on karni.models.BaseModel: `karni make model <Name>`."""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
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

    def __str__(self) -> str:
        return f"{self.quantity} x {self.tier} for {self.event}"

    @property
    def total(self) -> Decimal:
        return self.tier.price * self.quantity
