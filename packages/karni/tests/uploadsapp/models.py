"""Two models whose only difference is the kind of required upload.

``Photo`` has a required ``ImageField``, which DRF validates with Pillow, so
a text upload answers 400. ``Attachment`` has a required ``FileField``, which
takes any file. ``Photo.owner`` lets a viewset scope photos to their owner,
for the ``assert_isolated`` create probe. ``tests/testing/crud_urls.py`` routes
both models for the ``assert_crud`` suite, so the project-wide schema snapshot
never sees them.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from karni.models import BaseModel


class Photo(BaseModel):
    title = models.CharField(max_length=100)
    image = models.ImageField(upload_to="photos/")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    def __str__(self) -> str:
        return self.title


class Attachment(BaseModel):
    title = models.CharField(max_length=100)
    file = models.FileField(upload_to="attachments/")

    def __str__(self) -> str:
        return self.title
