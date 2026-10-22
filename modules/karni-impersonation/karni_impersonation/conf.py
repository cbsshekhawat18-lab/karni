"""Settings vocabulary for karni-impersonation: the ``karni.settings`` entry point.

Import-light by contract: plain data plus django-environ reads, never
``django.conf.settings`` at import time. Module code reads settings through
:func:`get`, so it also works without ``karni_settings()``.

Override / escape hatch: define any of these names in the project's
settings.py, or set the environment variable.
"""

from __future__ import annotations

from typing import Any

import environ
from django.conf import settings

env = environ.Env()

#: What an impersonator may never do, whatever the target may: viewset and
#: admin action names, ``app.model`` labels, ``app.model:action`` permission
#: keys (fnmatch patterns), and URL paths (patterns starting with ``/``).
DEFAULT_BLOCKED: list[str] = [
    "destroy",
    "delete",
    "delete_selected",
    "hard_delete_selected",
    "*:delete",
    "export",
    "export_csv",
    "export_xlsx",
    "import",
    "import_*",
    "karni_payments.*",
    "/api/auth/password/*",
    "/api/auth/email/*",
    "/api/auth/2fa/*",
    "/api/auth/register/",
]

DEFAULTS: dict[str, Any] = {
    # Hard limit on an impersonated session, which ends by itself after this.
    "KARNI_IMPERSONATION_MAX_MINUTES": env.int("KARNI_IMPERSONATION_MAX_MINUTES", default=60),
    # Actions, models, permissions and paths blocked while impersonating.
    "KARNI_IMPERSONATION_BLOCKED": env.list("KARNI_IMPERSONATION_BLOCKED", default=DEFAULT_BLOCKED),
    # A reason string is required to start (default on: this is customer data).
    "KARNI_IMPERSONATION_REQUIRE_REASON": env.bool(
        "KARNI_IMPERSONATION_REQUIRE_REASON", default=True
    ),
    # Email the impersonated user when a session starts (default on).
    "KARNI_IMPERSONATION_NOTIFY_TARGET": env.bool(
        "KARNI_IMPERSONATION_NOTIFY_TARGET", default=True
    ),
    # Sender address for that email, or "" to use DEFAULT_FROM_EMAIL.
    "KARNI_IMPERSONATION_FROM_EMAIL": env("KARNI_IMPERSONATION_FROM_EMAIL", default=""),
    # Inject the banner into every HTML page served to an impersonated session.
    "KARNI_IMPERSONATION_BANNER": env.bool("KARNI_IMPERSONATION_BANNER", default=True),
    # Where the admin's Impersonate button sends the impersonator afterwards.
    "KARNI_IMPERSONATION_LANDING": env("KARNI_IMPERSONATION_LANDING", default="/"),
}
"""The karni-impersonation settings fragment (``karni.settings`` entry point)."""


def get(name: str) -> Any:
    """``settings.<name>`` if the project defines it, else the module default."""
    return getattr(settings, name, DEFAULTS[name])
