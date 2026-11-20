"""The ``karni.demo`` app: registers the checks and the admin sign-in notice."""

from __future__ import annotations

from typing import Any

from django.apps import AppConfig


class KarniDemoConfig(AppConfig):
    """Experimental. Demo mode (see :mod:`karni.demo`)."""

    name = "karni.demo"
    label = "karni_demo_mode"
    verbose_name = "Public demo"

    def ready(self) -> None:
        """Register the checks, and let the admin's sign-in page show the demo accounts.

        While ``KARNI_DEMO_MODE`` is on at startup, the admin site's login page
        becomes ``demo/admin_login.html``, which extends Karni's own and lists
        the accounts. A site that already names another login template keeps it.
        With demo mode off the admin is untouched.
        """
        from django.contrib import admin

        from karni.demo import checks, conf  # noqa: F401 - checks registers the demo checks

        if conf.demo_mode():
            use_login_template(admin.site)


#: The admin login page that lists the demo accounts above Karni's own form.
LOGIN_TEMPLATE = "demo/admin_login.html"


def use_login_template(site: Any) -> None:
    """Point ``site`` at :data:`LOGIN_TEMPLATE` unless it names a login template of its own.

    Karni's admin app gives the site its login page first (``karni_admin/login.html``), and
    this page extends it, so that one is replaced. Any other name is the project's choice.
    """
    from karni.admin.apps import LOGIN_TEMPLATE as KARNI_LOGIN_TEMPLATE

    if getattr(site, "login_template", None) in (None, KARNI_LOGIN_TEMPLATE):
        site.login_template = LOGIN_TEMPLATE
