"""Settings for karni-site's standalone test suite (sqlite, eager Celery)."""

from __future__ import annotations

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

karni_settings(globals(), env_name="dev")

INSTALLED_APPS += ["karni_site"]  # type: ignore[name-defined]  # noqa: F821
TEMPLATES[0]["DIRS"] = [Path(__file__).resolve().parent / "templates"]  # type: ignore[name-defined]  # noqa: F821
