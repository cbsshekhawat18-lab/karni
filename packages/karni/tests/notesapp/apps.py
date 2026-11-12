"""App configuration for the notes test app."""

from __future__ import annotations

from django.apps import AppConfig


class NotesAppConfig(AppConfig):
    """Configuration for :mod:`tests.notesapp` (app label ``notesapp``)."""

    name = "tests.notesapp"
    label = "notesapp"
    verbose_name = "Karni family events test notes"
    default_auto_field = "django.db.models.BigAutoField"
