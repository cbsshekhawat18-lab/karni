"""Settings vocabulary for karni-approvals: the ``karni.settings`` entry point.

Import-light by contract: plain data plus django-environ reads, never
``django.conf.settings`` at import time. Module code reads settings through
:func:`get`, so it also works without ``karni_settings()``.

Every project-wide default here can be overridden per model in
``class Karni`` (``approvals_required``, ``approver_roles``,
``approval_timeout``, ``approval_on_timeout``, ``approval_escalation_roles``).

Override / escape hatch: define any of these names in the project's
settings.py, or set the environment variable.
"""

from __future__ import annotations

from typing import Any

import environ
from django.conf import settings

env = environ.Env()

DEFAULTS: dict[str, Any] = {
    # Approvals a pending change needs before it is applied (per model: approvals_required).
    "KARNI_APPROVALS_REQUIRED": env.int("KARNI_APPROVALS_REQUIRED", default=1),
    # Roles that may approve, on top of holding the approve permission; [] = any
    # holder of `karni_approvals.pendingchange:approve` (per model: approver_roles).
    "KARNI_APPROVALS_APPROVER_ROLES": env.list("KARNI_APPROVALS_APPROVER_ROLES", default=[]),
    # Hours before a pending change times out; 0 = never (per model: approval_timeout).
    "KARNI_APPROVALS_TIMEOUT_HOURS": env.int("KARNI_APPROVALS_TIMEOUT_HOURS", default=0),
    # What a timeout does: "expire" the change, or "escalate" (notify the escalation
    # roles and extend by the same timeout). Per model: approval_on_timeout.
    "KARNI_APPROVALS_ON_TIMEOUT": env("KARNI_APPROVALS_ON_TIMEOUT", default="expire"),
    # Roles notified on escalation (per model: approval_escalation_roles).
    "KARNI_APPROVALS_ESCALATION_ROLES": env.list("KARNI_APPROVALS_ESCALATION_ROLES", default=[]),
    # Dotted path called as fn(pending_change) from the Celery task to notify
    # the checkers; the default emails them. "" turns notification off.
    "KARNI_APPROVALS_NOTIFY": env(
        "KARNI_APPROVALS_NOTIFY", default="karni_approvals.notify.email_checkers"
    ),
    # Sender address for the default notifier; "" uses DEFAULT_FROM_EMAIL.
    "KARNI_APPROVALS_FROM_EMAIL": env("KARNI_APPROVALS_FROM_EMAIL", default=""),
}
"""The karni-approvals settings fragment (``karni.settings`` entry point)."""


def get(name: str) -> Any:
    """``settings.<name>`` if the project defines it, else the module default."""
    return getattr(settings, name, DEFAULTS[name])
