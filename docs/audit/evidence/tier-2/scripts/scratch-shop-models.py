"""shop models, each on karni.models.BaseModel: `karni make model <Name>`."""

from django.conf import settings
from django.db import models

from karni.models import (
    AuditedModel,
    BaseModel,
    SoftDeleteModel,
    TimestampedModel,
    UUIDModel,
)


class Venue(BaseModel):
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100)
    capacity = models.IntegerField()

    def __str__(self) -> str:
        return self.name


class Event(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE)
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True
    )

    def __str__(self) -> str:
        return self.title


class Tag(BaseModel):
    name = models.CharField(max_length=50)

    def __str__(self) -> str:
        return self.name


class Product(BaseModel):
    """Claim (c): no admin code anywhere for this model."""

    class Kind(models.TextChoices):
        PHYSICAL = "physical", "Physical"
        DIGITAL = "digital", "Digital"
        SERVICE = "service", "Service"

    name = models.CharField(max_length=120)
    sku = models.SlugField(max_length=40, unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PHYSICAL)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    in_stock = models.BooleanField(default=True)
    released_on = models.DateField(null=True, blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    venue = models.ForeignKey(Venue, null=True, blank=True, on_delete=models.SET_NULL)
    tags = models.ManyToManyField(Tag, blank=True)
    manual = models.FileField(upload_to="shop/product/manuals/", blank=True)
    photo = models.ImageField(upload_to="shop/product/photos/", blank=True)

    def __str__(self) -> str:
        return self.name


# Claim (a): each mixin standalone.
class OnlyUuid(UUIDModel):
    label = models.CharField(max_length=50)


class OnlyTimestamped(TimestampedModel):
    label = models.CharField(max_length=50)


class OnlySoftDelete(SoftDeleteModel):
    label = models.CharField(max_length=50)


class OnlyAudited(AuditedModel):
    label = models.CharField(max_length=50)


class Coupon(BaseModel):
    code = models.CharField(max_length=20)
    percent = models.IntegerField()
    expires_on = models.DateField(null=True, blank=True)

    def __str__(self) -> str:
        return self.code
