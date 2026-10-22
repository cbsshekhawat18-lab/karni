"""Django settings for karni's own test suite.

Exercises the exact flow a project's ``settings.py`` uses: pre-defined names
(``SECRET_KEY``, ``DATABASES``, ``CACHES``, media roots, Celery eager mode)
are never overwritten by :func:`karni.conf.karni_settings`, and everything
else falls back to Karni's dev-profile defaults.
"""

from __future__ import annotations

import tempfile

from karni.conf import karni_settings

# Pre-existing names win over every Karni default (setdefault semantics).
SECRET_KEY = "karni-tests-secret-key-not-for-production"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "karni-tests",
    },
}
MEDIA_ROOT = tempfile.mkdtemp(prefix="karni-tests-media-")
STATIC_ROOT = tempfile.mkdtemp(prefix="karni-tests-static-")

# Run Celery tasks inline during tests; no broker or worker required.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# The suite runs on sqlite, so swap the default Postgres full-text search
# provider for the portable icontains one (production keeps Postgres FTS).
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"

# Mounts admin/, api/auth/ and api/ for the accounts, api and admin suites.
ROOT_URLCONF = "tests.urls"

# Fast, insecure hashing keeps the user-heavy accounts tests quick.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

karni_settings(globals(), env_name="dev")

# Test-only apps exercised by the api (tests.testapp), admin (tests.adminapp),
# scope-pipeline (tests.scopeapp) and performance (tests.perfapp) suites;
# appended after the call, like a project would.
INSTALLED_APPS += [  # type: ignore[name-defined]  # noqa: F821
    "tests.testapp",
    "tests.adminapp",
    "tests.scopeapp",
    "tests.perfapp",
    # Typed field layer (karni.fields): portable fields, no viewsets.
    "tests.fieldsapp",
]
