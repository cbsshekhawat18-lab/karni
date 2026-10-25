"""App configuration for :mod:`karni.admin`.

``karni.admin`` must be listed *after* ``django.contrib.admin`` (Karni's
default ``INSTALLED_APPS`` does this): by the time :meth:`KarniAdminConfig.ready`
runs, every explicit registration — project ``admin.py`` modules imported by
contrib.admin's autodiscover and third-party apps' own admins — has already
happened, so Karni only fills the gaps. Apps listed *after* ``karni.admin``
whose ``ready()`` registers admins will raise ``AlreadyRegistered`` (Karni got
there first); keep ``karni.admin`` last or exclude their models via the
``KARNI_ADMIN_EXCLUDE`` setting.
"""

from __future__ import annotations

from typing import Any

from django.apps import AppConfig

#: The login template :class:`KarniAdminConfig` gives the admin site: unfold's
#: login page with the header's logo above the title.
LOGIN_TEMPLATE = "karni_admin/login.html"


class KarniAdminConfig(AppConfig):
    """Django app config wiring :func:`karni.admin.autodiscover` into startup.

    It also gives the admin site (``KARNI_ADMIN_SITE``) Karni's login
    template, which shows the header's logo (``KARNI_ADMIN_LOGO``) on the
    login screen, unless the site already sets ``login_template``.

    Override / escape hatch: set ``KARNI_ADMIN_AUTODISCOVER = False`` to skip
    the startup autodiscovery entirely (you can still call
    ``karni.admin.autodiscover()`` yourself), or narrow it with
    ``KARNI_ADMIN_EXCLUDE`` / per-model ``AdminMeta.exclude``. Set your
    site's ``login_template`` (or override ``karni_admin/login.html``) for
    another login page.
    """

    name = "karni.admin"
    label = "karni_admin"
    verbose_name = "Karni admin"

    def ready(self) -> None:
        """Give the site the logo login page, then auto-register unregistered models."""
        from django.conf import settings

        from karni.scoping import admin_site

        use_login_template(admin_site())
        if not getattr(settings, "KARNI_ADMIN_AUTODISCOVER", True):
            return

        from karni.admin import autodiscover

        autodiscover()


def use_login_template(site: Any) -> None:
    """Point ``site`` at :data:`LOGIN_TEMPLATE` unless it names a login template already."""
    if getattr(site, "login_template", None) is None:
        site.login_template = LOGIN_TEMPLATE
