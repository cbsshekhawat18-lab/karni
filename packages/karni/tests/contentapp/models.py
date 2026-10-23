"""The shape of a small site's content, for ``karni load`` (tests/transfer/test_loading.py).

* ``Service`` / ``Category`` / ``Project``: matched by their unique ``slug``
  (the natural key Karni infers).
* ``ProjectImage``: children of a project (``related_name="gallery"``),
  keyed by ``(project, position)`` through a unique constraint.
* ``Slide``: no natural key, matched on its unique constraint
  ``(placement, service, position)`` with a nullable foreign key.
* ``Member``: matched by a declared ``Karni.natural_key`` on a plain field.
  ``Member.projects`` names projects a content file lists later, so
  many-to-many fields must wait until every row exists. (No many-to-many
  cycle: one would change the order ``karni seed`` plans for every model.)
* ``Project.clean()`` refuses a year before 1900, as the API would.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from karni.models import BaseModel


class Service(BaseModel):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=100)
    image = models.ImageField(upload_to="services/", blank=True)

    def __str__(self) -> str:
        return self.title


class Category(BaseModel):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    key_services = models.ManyToManyField(Service, blank=True, related_name="categories")

    def __str__(self) -> str:
        return self.name


class Project(BaseModel):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=100)
    year = models.PositiveIntegerField(null=True, blank=True)
    published = models.BooleanField(default=False)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects"
    )
    services = models.ManyToManyField(Service, blank=True, related_name="projects")
    image = models.ImageField(upload_to="projects/", blank=True)

    def clean(self) -> None:
        if self.year is not None and self.year < 1900:
            raise ValidationError({"year": "year must be 1900 or later."})

    def __str__(self) -> str:
        return self.title


class ProjectImage(BaseModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="gallery")
    position = models.PositiveIntegerField()
    image = models.ImageField(upload_to="gallery/")  # required, as a gallery image is
    alt = models.CharField(max_length=200, blank=True, default="")

    class Meta(BaseModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "position"],
                condition=Q(deleted_at__isnull=True),
                name="contentapp_gallery_position",
            )
        ]

    def __str__(self) -> str:
        return f"{self.project} #{self.position}"


class Slide(BaseModel):
    placement = models.CharField(
        max_length=20, choices=[("home", "Home"), ("service", "Service page")]
    )
    service = models.ForeignKey(
        Service, null=True, blank=True, on_delete=models.CASCADE, related_name="slides"
    )
    position = models.PositiveIntegerField()
    heading = models.CharField(max_length=200)

    class Meta(BaseModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["placement", "service", "position"], name="contentapp_slide_place"
            )
        ]

    def __str__(self) -> str:
        return self.heading


class Member(BaseModel):
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=100, blank=True, default="")
    photo = models.ImageField(upload_to="team/", blank=True)
    projects = models.ManyToManyField(Project, blank=True, related_name="team")

    class Karni:
        natural_key = "name"

    def __str__(self) -> str:
        return self.name
