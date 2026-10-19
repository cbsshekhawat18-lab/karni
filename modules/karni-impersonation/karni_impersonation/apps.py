"""Django app configuration for ``karni_impersonation``."""

from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class KarniImpersonationConfig(AppConfig):
    """App config for the impersonation module (label ``karni_impersonation``).

    ``ready()`` registers the veto that blocks dangerous actions while
    impersonating, ends an impersonated session on logout, and adds the
    **Impersonate** button to the user admin when it is a django-unfold one.

    Override / escape hatch: subclass this config and point ``INSTALLED_APPS``
    at the subclass; keep the label so the shipped migrations keep applying.
    """

    name = "karni_impersonation"
    label = "karni_impersonation"
    verbose_name = "Karni impersonation"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from django.contrib.auth.signals import user_logged_out
        from karni.vetoes import register_veto

        from karni_impersonation.services import end_on_logout
        from karni_impersonation.vetoes import blocked_while_impersonating

        register_veto(blocked_while_impersonating, name="karni_impersonation")
        user_logged_out.connect(end_on_logout, dispatch_uid="karni_impersonation.logout")
        try:
            from karni_impersonation.admin import install_user_admin_button

            install_user_admin_button()
        except Exception:  # noqa: BLE001 - the button is a convenience, never a boot failure
            logger.warning(
                "karni_impersonation: could not add the Impersonate button", exc_info=True
            )
