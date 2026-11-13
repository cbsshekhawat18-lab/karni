"""Settings for karni-commerce's standalone test suite (sqlite, eager Celery, the test provider).

Names defined before :func:`karni.conf.karni_settings` win, and the
modules' own ``karni.settings`` fragments arrive through the merge.
``tests.testapp`` sells two kinds that are not a shop's products: gadgets
(stock, shipped) and workshop seats (no shipping, no refund once started).
"""

from __future__ import annotations

from karni.conf import karni_settings

SECRET_KEY = "karni-commerce-tests-secret-key-not-for-production"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
ROOT_URLCONF = "tests.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

KARNI_PAYMENTS_PROVIDER = "test"
KARNI_PAYMENTS_CURRENCY = "eur"
KARNI_PAYMENTS_CHECKOUT_VALIDATOR = "karni_commerce.payments.checkout_validator"
KARNI_FRONTEND_URL = "http://localhost:5173"
KARNI_COMMERCE_STAFF_EMAILS = ["orders@example.com"]

KARNI_ROLES = {
    "admin": {"name": "Admin", "system": True, "grants": {"*": "all"}},
    "clerk": {
        "name": "Clerk",
        "grants": {
            "karni_commerce.order:view": "all",
            "karni_commerce.order:change": "all",
            "karni_commerce.orderline:view": "all",
            "karni_commerce.cart:view": "all",
        },
    },
    "manager": {
        "name": "Manager",
        "grants": {"karni_commerce.*:*": "all"},
    },
    "customer": {"name": "Customer", "default": True, "grants": {}},
}

karni_settings(globals(), env_name="dev")

INSTALLED_APPS += ["karni_payments", "karni_commerce", "tests.testapp"]  # type: ignore[name-defined]  # noqa: F821
