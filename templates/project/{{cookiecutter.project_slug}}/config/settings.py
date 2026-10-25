"""Django settings for {{ cookiecutter.project_name }}.

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

from karni.conf import karni_settings

karni_settings(globals())

# --- Project apps ------------------------------------------------------------
INSTALLED_APPS += [  # noqa: F821
    # "myapp",
]  # karni:apps

# --- Project middleware (runs after Karni's stack) ----------------------------
MIDDLEWARE += [  # noqa: F821
    # "myapp.middleware.MyMiddleware",
]  # karni:middleware

# --- Project overrides -------------------------------------------------------
# Any Django/Karni setting assigned here beats the Karni default, e.g.:
# REST_FRAMEWORK["PAGE_SIZE"] = 25
# CELERY_TASK_TIME_LIMIT = 600
# FEATURE_X = env.bool("FEATURE_X", default=False)
# SILENCED_SYSTEM_CHECKS starts empty. Extend it to silence a check on purpose:
# SILENCED_SYSTEM_CHECKS += ["karni.W967"]
