"""Settings for karni-storage's standalone test suite (sqlite, eager Celery).

Names defined before :func:`karni.conf.karni_settings` win; the module's own
``karni.settings`` fragment arrives through the merge. ``tests.testapp`` is
the project under test: a ``Product`` with a protected manual (a PDF or text
file) and a protected photo, readable and writable by its owner only, and a
``Brochure`` no viewset serves. ``KARNI_TEST_PK=bigint`` puts the test app on
integer keys. Protected files go to a temporary directory, and the tests that
need a bucket switch ``KARNI_STORAGE`` to ``s3`` with a fake account (no
request leaves the process: signing is local and the bucket's answers are
stubbed).
"""

from __future__ import annotations

import tempfile

from karni.conf import karni_settings

SECRET_KEY = "karni-storage-tests-secret-key-not-for-production"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
ROOT_URLCONF = "tests.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

KARNI_STORAGE = "local"
MEDIA_ROOT = tempfile.mkdtemp(prefix="karni-storage-media-")
KARNI_STORAGE_ROOT = tempfile.mkdtemp(prefix="karni-storage-protected-")

# The fake account the bucket tests use (KARNI_STORAGE switched to "s3" per test).
AWS_ACCESS_KEY_ID = "AKIAKARNITEST"
AWS_SECRET_ACCESS_KEY = "karni-test-secret"
AWS_STORAGE_BUCKET_NAME = "karni-test-bucket"
AWS_S3_REGION_NAME = "eu-west-1"

karni_settings(globals(), env_name="dev")

INSTALLED_APPS += ["karni_storage", "tests.testapp"]  # type: ignore[name-defined]  # noqa: F821
