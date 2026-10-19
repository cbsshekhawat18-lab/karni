"""Settings for karni-impersonation's standalone test suite (sqlite, eager Celery)."""

from __future__ import annotations

from karni.conf import karni_settings

SECRET_KEY = "karni-impersonation-tests-secret-key-not-for-production"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
ROOT_URLCONF = "tests.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DEFAULT_FROM_EMAIL = "support@example.com"
KARNI_AUTH_MODE = "session"

KARNI_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "support": {
        "name": "Support",
        "grants": {
            "testapp.note:*": "all",
            "karni_accounts.user:view": "all",
            "karni_impersonation.impersonationsession:impersonate": "all",
            "karni_impersonation.impersonationsession:view": "all",
        },
    },
    "customer": {"name": "Customer", "grants": {"testapp.note:*": "own"}},
    "finance": {"name": "Finance", "grants": {"testapp.secret:view": "all"}},
}

karni_settings(globals(), env_name="dev")

INSTALLED_APPS += ["karni_impersonation", "tests.testapp"]  # type: ignore[name-defined]  # noqa: F821
MIDDLEWARE.insert(  # type: ignore[name-defined]  # noqa: F821
    MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware") + 1,  # type: ignore[name-defined]  # noqa: F821
    "karni_impersonation.middleware.ImpersonationMiddleware",
)
