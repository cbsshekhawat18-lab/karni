"""Settings for karni-reports' standalone test suite (sqlite, eager Celery, the fake renderer).

Names defined before :func:`karni.conf.karni_settings` win; the module's own
``karni.settings`` fragment arrives through the merge. ``tests.testapp`` is
the project under test: a product catalog whose products are owned by a user
and whose categories anyone may read. ``KARNI_TEST_PK=bigint`` puts its
models on integer keys.
"""

from __future__ import annotations

from karni.conf import karni_settings

SECRET_KEY = "karni-reports-tests-secret-key-not-for-production"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
ROOT_URLCONF = "tests.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
KARNI_AUTH_MODE = "session"
# Files live in memory: nothing is written to disk.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# No system library needed: deterministic bytes, and each render's HTML recorded.
KARNI_REPORTS_RENDERER = "fake"

KARNI_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
}

karni_settings(globals(), env_name="dev")

INSTALLED_APPS += ["karni_reports", "tests.testapp"]  # type: ignore[name-defined]  # noqa: F821
