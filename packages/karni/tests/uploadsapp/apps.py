"""App configuration for the uploads test app."""

from __future__ import annotations

from django.apps import AppConfig


class UploadsAppConfig(AppConfig):
    """Configuration for :mod:`tests.uploadsapp` (app label ``uploadsapp``)."""

    name = "tests.uploadsapp"
    label = "uploadsapp"
    verbose_name = "Karni uploads test app"
