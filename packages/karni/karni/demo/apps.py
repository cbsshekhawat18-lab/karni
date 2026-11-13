"""The ``karni.demo`` app: registers the checks and the admin sign-in notice."""

from __future__ import annotations

from django.apps import AppConfig


class KarniDemoConfig(AppConfig):
    """Experimental. Demo mode (see :mod:`karni.demo`)."""

    name = "karni.demo"
    label = "karni_demo"
    verbose_name = "Public demo"

    def ready(self) -> None:
        """Register the checks, and let the admin's sign-in page show the demo accounts.

        Karni's admin app gives the site its login page first, and this one
        extends it (``demo/admin_login.html``). While ``KARNI_DEMO_MODE`` is off
        the page is Karni's unchanged.
        """
        from django.contrib import admin

        from karni.demo import checks  # noqa: F401 - registers the demo checks

        admin.site.login_template = "demo/admin_login.html"
