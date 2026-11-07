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


class Project(BaseModel):
    """A row with a page, a photo and a summary: the SEO tests' detail pages and cards."""

    title = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    summary = models.TextField(blank=True)
    photo = models.ImageField(upload_to="projects/", blank=True)
    published = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        ordering: ClassVar[list[str]] = ["title"]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return f"/projects/{self.slug}/"


class Note(BaseModel):
    """A row with a page that the sitemap leaves out (class Karni: sitemap = False)."""

    title = models.CharField(max_length=100)

    class Karni:
        sitemap = False

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return f"/notes/{self.pk}/"


class Article(BaseModel):
    """A row published by its status and its date: the sitemap's filters without a declaration."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    title = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return f"/articles/{self.pk}/"
