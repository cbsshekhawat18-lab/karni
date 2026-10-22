"""Settings vocabulary for karni-payments.

:data:`DEFAULTS` is the module's **settings fragment**: it is exposed through
the ``karni.settings`` entry point (see this module's ``pyproject.toml``), so
:func:`karni.conf.karni_settings` merges it into every project's settings
automatically — after Karni's BASE/profile defaults and before project
overrides, new top-level names only.

The fragment is import-light on purpose: plain data plus django-environ
reads, and it never touches ``django.conf.settings`` at import time.
Per-profile values would read ``os.environ["DJANGO_ENV"]`` here directly —
the documented hatch, since fragments merge before profiles are observable.

:func:`get` is the accessor every ``karni_payments`` module reads settings
through — ``getattr(settings, name, DEFAULTS[name])`` — so the module also
works in projects that configure Django without ``karni_settings()`` (the
fragment merge is convenience, not correctness).

Override / escape hatch: define any of these names in your ``settings.py``
(before or after ``karni_settings()``) or set the matching environment
variable; provider credentials default to ``""`` and are validated lazily at
provider use, never at boot.
"""

from __future__ import annotations

from typing import Any

import environ
from django.conf import settings

env = environ.Env()

DEFAULTS: dict[str, Any] = {
    # Active provider: "stripe", "razorpay", "test" or any dotted path to a
    # karni_payments.providers.base.PaymentProvider subclass (the escape
    # hatch for custom gateways).
    "KARNI_PAYMENTS_PROVIDER": env("KARNI_PAYMENTS_PROVIDER", default="stripe"),
    # Default ISO currency code used when create_checkout gets none.
    "KARNI_PAYMENTS_CURRENCY": env("KARNI_PAYMENTS_CURRENCY", default="usd"),
    # Dotted path called with (user=, amount=, currency=, metadata=) BEFORE a
    # Payment is created. It is the server-side pricing authority. The default
    # is a pass-through, and production projects should replace it (never
    # trust client amounts).
    "KARNI_PAYMENTS_CHECKOUT_VALIDATOR": ("karni_payments.services.default_checkout_validator"),
    # Dotted path of the webhook state machine applied by the Celery task.
    "KARNI_PAYMENTS_EVENT_HANDLER": "karni_payments.services.apply_event",
    # Extra URLs whose origins are allowed as checkout success/cancel
    # redirects, on top of KARNI_FRONTEND_URL's origin.
    "KARNI_PAYMENTS_ALLOWED_REDIRECTS": env.list("KARNI_PAYMENTS_ALLOWED_REDIRECTS", default=[]),
    # Provider credentials: blank by default, validated lazily at use.
    "STRIPE_SECRET_KEY": env("STRIPE_SECRET_KEY", default=""),
    "STRIPE_WEBHOOK_SECRET": env("STRIPE_WEBHOOK_SECRET", default=""),
    "RAZORPAY_KEY_ID": env("RAZORPAY_KEY_ID", default=""),
    "RAZORPAY_KEY_SECRET": env("RAZORPAY_KEY_SECRET", default=""),
    "RAZORPAY_WEBHOOK_SECRET": env("RAZORPAY_WEBHOOK_SECRET", default=""),
}
"""The karni-payments settings fragment (``karni.settings`` entry point)."""


def get(name: str) -> Any:
    """Return the effective value of a karni-payments setting.

    Project settings win; :data:`DEFAULTS` is the fallback, so the accessor
    works whether or not the project assembled its settings through
    ``karni_settings()``.

    :raises KeyError: when ``name`` is not a karni-payments setting and the
        project has not defined it either.
    """
    return getattr(settings, name, DEFAULTS[name])
