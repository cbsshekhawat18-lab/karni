"""Settings for karni-site's standalone test suite (sqlite, eager Celery)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from karni.conf import karni_settings

SECRET_KEY = "karni-site-tests-secret-key-not-for-production"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
ROOT_URLCONF = "tests.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "site@example.com"
# Who hears about a new appointment request (tests/formapp/listeners.py).
APPOINTMENT_RECIPIENTS = ["desk@example.com", "doctor@example.com"]

karni_settings(globals(), env_name="dev")

INSTALLED_APPS += ["karni_site", "tests.testapp", "tests.formapp"]  # type: ignore[name-defined]  # noqa: F821
MIDDLEWARE += ["karni_site.middleware.RedirectMiddleware"]  # type: ignore[name-defined]  # noqa: F821
TEMPLATES[0]["DIRS"] = [Path(__file__).resolve().parent / "templates"]  # type: ignore[name-defined]  # noqa: F821
TEMPLATES[0]["OPTIONS"]["context_processors"] += ["karni_site.context_processors.site"]  # type: ignore[name-defined]  # noqa: F821
MEDIA_ROOT = tempfile.mkdtemp(prefix="karni-site-media-")
ALLOWED_HOSTS = ["testserver", "www.example.com"]
