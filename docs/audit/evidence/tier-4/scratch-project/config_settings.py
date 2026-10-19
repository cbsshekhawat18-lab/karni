"""Django settings for audit4.

karni_settings() fills this module with Karni's defaults — INSTALLED_APPS,
middleware, DRF, Celery, Redis cache, storage, logging, security headers,
CORS and Sentry — all read from environment variables (see .env.example).

Overriding: anything assigned *after* the call wins, and any name defined
*before* the call is never overwritten by Karni.
"""

from karni.conf import karni_settings

karni_settings(globals())

# --- Project apps ------------------------------------------------------------
INSTALLED_APPS += [  # noqa: F821
    # "myapp",
    "events",
    "karni_payments",
]  # karni:apps

# --- Project middleware (runs after Karni's stack) ----------------------------
MIDDLEWARE += [  # noqa: F821
    # "myapp.middleware.MyMiddleware",
]  # karni:middleware

# --- Project overrides -------------------------------------------------------
# Any Django/Karni setting assigned here beats the Karni default, e.g.:
# REST_FRAMEWORK["PAGE_SIZE"] = 25
# CELERY_TASK_TIME_LIMIT = 600

# audit4: the in-memory test provider for the webhook audit (docs: modules/karni-payments/README.md)
KARNI_PAYMENTS_PROVIDER = "test"
KARNI_API_ROUTER = "config.api.get_router"  # audit4: explicit routes for the audit viewsets
