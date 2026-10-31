"""The thumbnails made of protected images, one row per image and size.

A thumbnail is a file in the protected storage like its image. Its row says
which image (``source``, the image's name in the storage) and which size of
``KARNI_STORAGE_THUMBNAIL_SIZES`` it is, and where the thumbnailer saved it
(``name``), so a project's own thumbnailer (``KARNI_THUMBNAILER``) may name
its files as it likes. The download path finds a thumbnail through this row.

Override / escape hatch: thumbnails are made by
:func:`karni_storage.thumbnails.make`, which uses core's thumbnailer
(``KARNI_THUMBNAILER``). The admin is derived from ``AdminMeta``.
"""

from __future__ import annotations

from django.db import models
from karni.models import BaseModel

__all__ = ["Thumbnail"]


class Thumbnail(BaseModel):
    """Experimental. One thumbnail of one protected image."""

    source = models.CharField(max_length=500, db_index=True)
    size = models.CharField(max_length=40)
    name = models.CharField(max_length=500)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "size"], name="karni_storage_thumbnail_source_size"
            )
        ]

    class AdminMeta:
        list_display = ["source", "size", "name", "created_at"]
        search_fields = ["source"]
        read_only = ["source", "size", "name"]

    def __str__(self) -> str:
        return f"{self.source} ({self.size})"
