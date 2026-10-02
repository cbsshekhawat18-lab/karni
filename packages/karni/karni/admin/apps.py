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

from django.apps import AppConfig


class KarniAdminConfig(AppConfig):
    """Django app config wiring :func:`karni.admin.autodiscover` into startup.

    Override / escape hatch: set ``KARNI_ADMIN_AUTODISCOVER = False`` to skip
    the startup autodiscovery entirely (you can still call
    ``karni.admin.autodiscover()`` yourself), or narrow it with
    ``KARNI_ADMIN_EXCLUDE`` / per-model ``AdminMeta.exclude``.
    """

    name = "karni.admin"
    label = "karni_admin"
    verbose_name = "Karni admin"

    def ready(self) -> None:
        """Auto-register unregistered models unless the setting disables it."""
        from django.conf import settings

        if not getattr(settings, "KARNI_ADMIN_AUTODISCOVER", True):
            return

        from karni.admin import autodiscover

        autodiscover()
