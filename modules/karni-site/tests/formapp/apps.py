from __future__ import annotations

from django.apps import AppConfig


class FormappConfig(AppConfig):
    name = "tests.formapp"
    label = "formapp"
    default_auto_field = "django.db.models.BigAutoField"
