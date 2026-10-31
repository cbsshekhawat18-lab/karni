"""Django app configuration for ``karni_storage``."""

from __future__ import annotations

from django.apps import AppConfig


class KarniStorageConfig(AppConfig):
    """App config for the Karni storage module (label ``karni_storage``).

    ``ready()`` maps the protected model fields to their serializer fields in
    DRF's ``ModelSerializer.serializer_field_mapping``, so every model
    serializer (Karni's generated ones and a project's own) gives the
    download path and takes upload tokens, and loads the OpenAPI extension.

    Override / escape hatch: subclass this config and point ``INSTALLED_APPS``
    at it to change startup; the label must stay ``karni_storage`` so the
    shipped migrations keep applying. A serializer that declares the field
    itself is left alone.
    """

    name = "karni_storage"
    label = "karni_storage"
    verbose_name = "Karni storage"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from rest_framework.serializers import ModelSerializer

        from karni_storage import serializers
        from karni_storage.fields import ProtectedFileField, ProtectedImageField

        mapping = ModelSerializer.serializer_field_mapping
        mapping.setdefault(ProtectedFileField, serializers.ProtectedFileSerializerField)
        mapping.setdefault(ProtectedImageField, serializers.ProtectedImageSerializerField)
