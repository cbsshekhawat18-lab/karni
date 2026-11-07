"""Settings for karni-ai's standalone test suite (sqlite, eager Celery, the test provider).

Names defined before :func:`karni.conf.karni_settings` win. The module's own
``karni.settings`` fragment arrives through the merge. ``tests.testapp`` is
the project under test: a product catalog with categories and tags (natural
keys), products an ``editor`` creates, and a resource whose import is off.
"""

from __future__ import annotations

from karni.conf import karni_settings

SECRET_KEY = "karni-ai-tests-secret-key-not-for-production"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
ROOT_URLCONF = "tests.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# Import jobs store their file in the default storage: keep it in memory.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# The deterministic provider: the whole pipeline, no network and no key.
KARNI_AI_PROVIDER = "test"
KARNI_AI_PRICES = {"test": {"input": "2.00", "output": "8.00"}}

KARNI_ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    "editor": {
        "name": "Editor",
        "grants": {"testapp.*:*": "all"},
    },
    "buyer": {
        "name": "Buyer",
        "grants": {"testapp.category:*": "all", "testapp.product:view": "all"},
    },
}

karni_settings(globals(), env_name="dev")

INSTALLED_APPS += ["karni_ai", "tests.testapp"]  # type: ignore[name-defined]  # noqa: F821
