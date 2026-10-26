"""A small project beside the site: services with their own pages, and enquiries."""

from __future__ import annotations

from typing import ClassVar

from django.db import models
from django.urls import reverse
from karni.models import BaseModel


class Service(BaseModel):
    title = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    published = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["order", "title"]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("website:service", kwargs={"slug": self.slug})


class Enquiry(BaseModel):
    name = models.CharField(max_length=100)
    message = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name
