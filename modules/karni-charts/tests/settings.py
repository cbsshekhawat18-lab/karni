"""Settings for karni-charts' standalone test suite (sqlite, eager Celery).

Names defined before :func:`karni.conf.karni_settings` win, and the module's
own ``karni.settings`` fragment arrives through the merge. ``tests.testapp``
is the project under test: a product catalog whose ``Product`` declares an
aggregation, read by the ``analyst`` role and by each product's owner.
"""

from __future__ import annotations

from karni.conf import karni_settings

SECRET_KEY = "karni-charts-tests-secret-key-not-for-production"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
ROOT_URLCONF = "tests.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

KARNI_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "analyst": {
        "name": "Analyst",
        "grants": {"testapp.*:view": "all", "karni_charts.chart:view": "all"},
    },
    "user": {"name": "User", "grants": {"*": "own"}},
}

karni_settings(globals(), env_name="dev")

INSTALLED_APPS += ["karni_charts", "tests.testapp"]  # type: ignore[name-defined]  # noqa: F821
