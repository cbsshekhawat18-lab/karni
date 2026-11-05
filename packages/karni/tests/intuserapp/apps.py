from __future__ import annotations

from django.apps import AppConfig


class IntUserAppConfig(AppConfig):
    """An integer-keyed user model, installed only with ``KARNI_TEST_USER_PK=bigint``."""

    name = "tests.intuserapp"
    label = "intuserapp"
    default_auto_field = "django.db.models.BigAutoField"
