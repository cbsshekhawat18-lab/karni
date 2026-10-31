"""Django settings for karni's own test suite.

Exercises the exact flow a project's ``settings.py`` uses: pre-defined names
(``SECRET_KEY``, ``DATABASES``, ``CACHES``, media roots, Celery eager mode)
are never overwritten by :func:`karni.conf.karni_settings`, and everything
else falls back to Karni's dev-profile defaults.
"""

from __future__ import annotations

import os
import tempfile

from karni.conf import karni_settings

# Pre-existing names win over every Karni default (setdefault semantics).
SECRET_KEY = "karni-tests-secret-key-not-for-production"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
    # The second database of the external tables suite (tests.externalapp,
    # class Karni: database = "second"). Created only for tests that ask for it.
    "second": {
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
# karni_check's cache writes to the project (.karni/local/): its own tests turn it on.
KARNI_CHECK_CACHE = False
# karni_seed's ledger too (.karni/local/seeded.json): the volume tests point it at a tmp file.
KARNI_SEED_LEDGER = False

# Mounts admin/, api/auth/ and api/ for the accounts, api and admin suites.
ROOT_URLCONF = "tests.urls"

# Fast, insecure hashing keeps the user-heavy accounts tests quick.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

karni_settings(globals(), env_name="dev")

# Test-only apps exercised by the api (tests.testapp), admin (tests.adminapp),
# scope-pipeline (tests.scopeapp), performance (tests.perfapp), lifecycle /
# limited-resource (tests.lifecycleapp) and upload (tests.uploadsapp) suites,
# appended after the call, like a project would.
INSTALLED_APPS += [  # type: ignore[name-defined]  # noqa: F821
    "tests.testapp",
    "tests.adminapp",
    "tests.scopeapp",
    "tests.perfapp",
    # Typed field layer (karni.fields): portable fields, no viewsets.
    "tests.fieldsapp",
    "tests.lifecycleapp",
    # Required FileField and ImageField (assert_crud's uploads), no routed viewsets.
    "tests.uploadsapp",
    # Content loading (karni load): no viewsets, so the API never sees it.
    "tests.contentapp",
    # External tables, a SQL view and a second database (karni.db): viewsets
    # mounted by its own URLconf only.
    "tests.externalapp",
]

# An integer-keyed user model (tests/intuserapp), for the accounts flows that
# tests/accounts/test_integer_user.py runs in a subprocess with this variable.
if os.environ.get("KARNI_TEST_USER_PK") == "bigint":
    INSTALLED_APPS += ["tests.intuserapp"]  # type: ignore[name-defined]  # noqa: F821
    AUTH_USER_MODEL = "intuserapp.User"
    # The 2FA login gate is one of the flows: its apps, when karni[2fa] is installed.
    import importlib.util

    if importlib.util.find_spec("django_otp") is not None:
        INSTALLED_APPS += ["django_otp", "django_otp.plugins.otp_totp"]  # type: ignore[name-defined]  # noqa: F821
