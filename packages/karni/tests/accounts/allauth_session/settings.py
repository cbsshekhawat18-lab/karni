"""Settings of the coexistence project: session mode, allauth's Google flow and ID tokens."""

from __future__ import annotations

from karni.conf import karni_settings

SECRET_KEY = "karni-tests-allauth-session-not-for-production"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
ROOT_URLCONF = "tests.accounts.allauth_session.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
KARNI_DEBUG_CAPTURE = False

KARNI_AUTH_MODE = "session"
KARNI_SOCIAL_AUTH = True
KARNI_SOCIAL_PROVIDERS = ["google"]
SOCIALACCOUNT_PROVIDERS = {"google": {"APP": {"client_id": "allauth-client", "secret": "s"}}}

KARNI_SOCIAL_TOKEN_PROVIDERS = {"google": {"client_ids": ["web-client.apps.example.test"]}}
KARNI_SOCIAL_TOKEN_JWKS_FETCHER = "tests.accounts.idtokens.fake_fetch"

karni_settings(globals(), env_name="dev")
