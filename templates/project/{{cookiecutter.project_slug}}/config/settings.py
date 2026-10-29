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

from pathlib import Path

from karni.conf import karni_settings

# The project folder. Karni reads relative paths from it (MEDIA_ROOT in
# development, content/site.json in tests), whatever folder a command runs in.
BASE_DIR = Path(__file__).resolve().parent.parent

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
{%- if cookiecutter.kind == "site" %}

# --- A public website (kind "site" in pyproject.toml) -------------------------
# Nobody opens an account: staff create them in the admin, and the editor role
# (karni-site's) is for people who only change the site's content.
# KARNI_ACCOUNTS_REGISTRATION=True in .env opens registration.
KARNI_ACCOUNTS_REGISTRATION = env.bool(  # noqa: F821
    "KARNI_ACCOUNTS_REGISTRATION", default=False
)
# Staff, and the editor role karni-site declares. The roles an app gives the
# people who sign up (user, customer) are left out.
KARNI_ROLES = {"staff": KARNI_ROLES["staff"]}  # noqa: F821
{%- endif %}
{%- if cookiecutter.staff_app == "no" %}

# No staff app (frontend/): the admin wears the design's colours and fonts from
# this file, which `karni import design` and `karni ui detect --css` write.
KARNI_THEME_CSS = "karni-theme.css"
{%- endif %}
