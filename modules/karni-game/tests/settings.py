"""Settings for karni-game's standalone test suite (sqlite, eager Celery).

Names defined before :func:`karni.conf.karni_settings` win, and the
modules' own ``karni.settings`` fragments arrive through the merge.
"""

from __future__ import annotations

from karni.conf import karni_settings

SECRET_KEY = "karni-game-tests-secret-key-not-for-production"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KARNI_SEARCH_PROVIDER = "karni.api.search.simple.SimpleSearchProvider"
ROOT_URLCONF = "tests.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
KARNI_FRONTEND_URL = "http://localhost:5173"
# A player is the game profile of a person (karni.GAME001).
KARNI_PEOPLE = True
KARNI_GAME_SERVER_SECRET = "karni-game-tests-server-secret"
KARNI_GAME_PORTALS = {"arcade": {"secret": "arcade-portal-test-secret"}}
# karni-commerce sells the real-money items (the sellable kind game_item).
KARNI_PAYMENTS_PROVIDER = "test"
KARNI_PAYMENTS_CURRENCY = "eur"
KARNI_PAYMENTS_CHECKOUT_VALIDATOR = "karni_commerce.payments.checkout_validator"
KARNI_PREFERENCES_LOCKED = {"details": {"currency": "EUR"}}

KARNI_ROLES = {
    "admin": {"name": "Admin", "system": True, "grants": {"*": "all"}},
    "customer": {"name": "Customer", "default": True, "grants": {}},
}

karni_settings(globals(), env_name="dev")

# karni.outbox and karni.timeline: the family events and the entries they write.
# karni.preferences: the Games section. karni.notify: the inbox of an unlocked achievement.
# karni_payments and karni_commerce: real-money items (optional in a project).
INSTALLED_APPS += [  # type: ignore[name-defined]  # noqa: F821
    "karni.outbox",
    "karni.timeline",
    "karni.preferences",
    "karni.notify",
    "karni_payments",
    "karni_commerce",
    "karni_game",
]
