"""The ``payments-admin`` role this module declares (the ``karni.roles`` entry point).

The role sees every payment and refund (the API's owner scope does not apply
to it), issues refunds, and reads the webhook log. It is synced by ``karni
migrate`` once the module is installed, so a project writes nothing in
``KARNI_ROLES``. Give a person the role to let them refund.

Override / escape hatch: a ``payments-admin`` entry in ``KARNI_ROLES`` replaces
this one, and the permission matrix changes its grants without a deploy.
"""

from __future__ import annotations

from typing import Any

__all__ = ["declared"]

ROLE = "payments-admin"


def declared() -> dict[str, Any]:
    """``{slug: spec}`` for ``KARNI_ROLES``' merge, or ``{}`` when the app is not installed."""
    from django.apps import apps

    if not apps.ready or not apps.is_installed("karni_payments"):
        return {}
    return {
        ROLE: {
            "name": "Payments admin",
            "description": (
                "Sees every payment and refund, issues refunds and reads the webhook log."
            ),
            "grants": {
                "karni_payments.payment:view": "all",
                "karni_payments.refund:view": "all",
                "karni_payments.webhookevent:view": "all",
            },
        }
    }
