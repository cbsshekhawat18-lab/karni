"""Django settings for Social Leads.

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
    "crm",
]  # karni:apps

# --- Project middleware (runs after Karni's stack) ----------------------------
MIDDLEWARE += [  # noqa: F821
    # "myapp.middleware.MyMiddleware",
]  # karni:middleware

# --- Project overrides -------------------------------------------------------
# Any Django/Karni setting assigned here beats the Karni default, e.g.:
# REST_FRAMEWORK["PAGE_SIZE"] = 25
# CELERY_TASK_TIME_LIMIT = 600

# Roles (ADR 0002): staff sees everything; a member sees the rows of the
# workspaces they belong to (`own` through each model's owner_field path).
KARNI_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "member": {"name": "Workspace member", "grants": {"crm.*:*": "own"}},
}
