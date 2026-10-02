"""Models for the performance suites.

A four-level publishing graph exercises the optimizer at three nested levels
in both directions:

* ``Publisher`` ← ``Writer`` ← ``Novel`` ← ``Chapter`` (reverse FKs, nested
  ``many=True`` serializers going down);
* ``Chapter`` → ``Novel`` → ``Writer`` → ``Publisher`` (forward FKs, nested
  to-one serializers going up);
* ``Novel`` ↔ ``Genre`` (M2M; ``Genre`` has an explicit factory in
  ``factories.py``).

``Specimen`` carries one field of every shape :mod:`karni.testing.factories`
generates a value for; ``Loop`` has a required self-reference (unbuildable).
"""

from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from karni.models import BaseModel


class Publisher(BaseModel):
    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class Genre(BaseModel):
    name = models.CharField(max_length=50, unique=True)

    class Meta(BaseModel.Meta):
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Writer(BaseModel):
    name = models.CharField(max_length=100)
    publisher = models.ForeignKey(Publisher, on_delete=models.CASCADE, related_name="writers")

    def __str__(self) -> str:
        return self.name


class Novel(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OUT = "out", "Published"

    title = models.CharField(max_length=200)
    writer = models.ForeignKey(Writer, on_delete=models.CASCADE, related_name="novels")
    genres = models.ManyToManyField(Genre, blank=True, related_name="novels")
    status = models.CharField(max_length=10, choices=Status.choices)

    class APIMeta:
        select = ["writer"]

    def __str__(self) -> str:
        return self.title

    @property
    def writer_name(self) -> str:
        return self.writer.name


class Chapter(BaseModel):
    novel = models.ForeignKey(Novel, on_delete=models.CASCADE, related_name="chapters")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=100)

    class Meta(BaseModel.Meta):
        ordering = ("number",)
        constraints = [
            models.UniqueConstraint(fields=["novel", "number"], name="perfapp_chapter_unique")
        ]

    def __str__(self) -> str:
        return self.title


class Specimen(BaseModel):
    class Size(models.IntegerChoices):
        SMALL = 1, "Small"
        LARGE = 2, "Large"

    label = models.CharField(max_length=12, unique=True)
    slug = models.SlugField(max_length=20)
    email = models.EmailField(unique=True)
    url = models.URLField()
    address = models.GenericIPAddressField()
    body = models.TextField()
    flag = models.BooleanField()
    size = models.PositiveSmallIntegerField(choices=Size.choices)
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    weight = models.FloatField()
    price = models.DecimalField(max_digits=5, decimal_places=2)
    day = models.DateField()
    moment = models.DateTimeField()
    clock = models.TimeField()
    span = models.DurationField()
    token = models.UUIDField()
    payload = models.JSONField()
    attachment = models.FileField(upload_to="specimens/")
    note = models.CharField(max_length=50, null=True, blank=True)
    nickname = models.CharField(max_length=20, null=True)
    count = models.IntegerField(default=7)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    publisher = models.OneToOneField(Publisher, on_delete=models.CASCADE, related_name="specimen")
    genres = models.ManyToManyField(Genre, blank=True, related_name="specimens")

    def __str__(self) -> str:
        return self.label


class Loop(BaseModel):
    """A required self-reference: no generated factory can build one."""

    partner = models.ForeignKey("self", on_delete=models.CASCADE, related_name="+")
