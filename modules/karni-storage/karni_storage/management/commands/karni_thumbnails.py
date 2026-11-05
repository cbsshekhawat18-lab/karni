"""``manage.py karni_thumbnails``: make the thumbnails protected images are missing.

Walks every model with a protected image field that makes thumbnails and
makes the missing sizes of each stored image, in this process (no worker
needed). Run it after adding a size to ``KARNI_STORAGE_THUMBNAIL_SIZES`` or
when the worker was down.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Make the thumbnails protected images are missing (karni-storage)."

    def handle(self, *args: Any, **options: Any) -> None:
        from django.apps import apps

        from karni_storage.fields import protected_fields
        from karni_storage.thumbnails import make

        made = 0
        for model in apps.get_models():
            for field in protected_fields(model):
                if not field.makes_thumbnails:
                    continue
                names = (
                    model._default_manager.exclude(**{field.attname: ""})
                    .exclude(**{f"{field.attname}__isnull": True})
                    .values_list(field.attname, flat=True)
                )
                for name in names.iterator():
                    made += len(make(str(name)))
        self.stdout.write(f"karni_thumbnails: {made} made.")
