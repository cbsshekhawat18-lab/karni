"""Django settings for karni-payments' standalone test suite.

Exercises the exact flow a project's ``settings.py`` uses: names defined
before :func:`karni.conf.karni_settings` win (sqlite, locmem cache, eager
Celery, the TestProvider); everything else — including the module's own
``karni.settings`` fragment — arrives through the merge.
"""

from __future__ import annotations

from karni.conf import karni_settings

SECRET_KEY = "karni-payments-tests-secret-key-not-for-production"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "karni-payments-tests",
    },
}

# Run Celery tasks inline during tests; no broker or worker required.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# The in-memory deterministic provider — the whole pipeline, no gateway.
KARNI_PAYMENTS_PROVIDER = "test"

# sqlite suite: swap the Postgres FTS provider for the portable one.
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"

ROOT_URLCONF = "tests.urls"

# Fast, insecure hashing keeps user-heavy tests quick.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

karni_settings(globals(), env_name="dev")

INSTALLED_APPS += ["karni_payments"]  # type: ignore[name-defined]  # noqa: F821
