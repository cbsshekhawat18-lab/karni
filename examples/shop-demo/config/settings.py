"""Django settings for Shop Demo.

karni_settings() fills this module with Karni's defaults: INSTALLED_APPS,
middleware, DRF, Celery, Redis cache, storage, logging, security headers,
CORS and Sentry, all read from environment variables (see .env.example).

Overriding: anything assigned *after* the call wins, and any name defined
*before* the call is never overwritten by Karni. The call also leaves `env`
here: the django-environ reader Karni reads its defaults with, so a setting
added below can come from .env the same way.

The exception: the call reads KARNI_AUTH_MODE, KARNI_2FA, KARNI_SOCIAL_AUTH,
KARNI_SOCIAL_PROVIDERS, KARNI_FRONTEND_URL, KARNI_AUTH_THROTTLE_RATES,
KARNI_JSON_LOGS, KARNI_CACHE and KARNI_STORAGE to compute other settings.
Set those in .env, above the call, or as karni_settings(globals(), NAME=...).
Assigned below the call they change nothing, and startup fails with
karni.E508. See docs/settings.md.
"""

from pathlib import Path

from karni.conf import karni_settings

# The project folder. Karni reads relative paths from it (MEDIA_ROOT in
# development, content/site.json in tests), whatever folder a command runs in.
BASE_DIR = Path(__file__).resolve().parent.parent

# karni:spec start
# Roles, features and module options from karni.yaml. Change them there and run
# karni build: it rewrites the lines between the markers.
KARNI_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "customer": {
        "name": "Customer",
        "grants": {
            "shop.cart:*": "own",
            "shop.cartitem:*": "own",
            "shop.order:*": "own",
            "shop.orderitem:*": "own",
        },
    },
}
KARNI_ACCOUNTS_DEFAULT_ROLES = ["customer"]
KARNI_2FA = False
KARNI_EMAIL_OTP = True
KARNI_SOCIAL_TOKEN_PROVIDERS = {}
KARNI_TERMS = {"version": "2026-01", "url": "/terms/"}
KARNI_USER_GRANTS = False
KARNI_PAYMENTS_PROVIDER = "stripe"
KARNI_PAYMENTS_CURRENCY = "usd"
# karni:spec end

karni_settings(globals())

# --- Project apps ------------------------------------------------------------
INSTALLED_APPS += [  # noqa: F821
    # "myapp",
    "karni_payments",
    "shop",
]  # karni:apps

# --- Project middleware (runs after Karni's stack) ----------------------------
MIDDLEWARE += [  # noqa: F821
    # "myapp.middleware.MyMiddleware",
]  # karni:middleware

# A new project never read the deprecated X-Karni-Cache header, so it is not sent.
# Existing projects keep sending it, with a deprecation warning, until 1.0.
KARNI_API_CACHE_LEGACY_HEADER = env.bool("KARNI_API_CACHE_LEGACY_HEADER", default=False)  # noqa: F821

# --- Project overrides -------------------------------------------------------
# Any Django/Karni setting assigned here beats the Karni default, e.g.:
# REST_FRAMEWORK["PAGE_SIZE"] = 25
# CELERY_TASK_TIME_LIMIT = 600
# FEATURE_X = env.bool("FEATURE_X", default=False)
# SILENCED_SYSTEM_CHECKS starts empty. Extend it to silence a check on purpose:
# SILENCED_SYSTEM_CHECKS += ["karni.W967"]
