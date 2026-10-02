"""App configuration for the admin test app."""

from __future__ import annotations

from django.apps import AppConfig


class AdminAppConfig(AppConfig):
    """Configuration for :mod:`tests.adminapp` (app label ``adminapp``).

    Listed *after* ``karni.admin`` in the test settings on purpose: explicit
    registrations still happen first because ``django.contrib.admin``'s own
    autodiscovery imports every app's ``admin`` module during *its* ``ready()``,
    which runs before ``karni.admin``'s.
    """

    name = "tests.adminapp"
    label = "adminapp"
    verbose_name = "Karni admin test app"
