"""Karni base settings profile.

:data:`BASE` holds every profile-independent default that
:func:`karni.conf.karni_settings` merges into a project's settings namespace.
All values are plain data (strings, numbers, lists, dicts and stdlib values
such as :class:`datetime.timedelta`) so the module imports without Django
being configured, and ``karni_settings()`` deep-copies the dict on every call
so mutating a project's settings never corrupts these module-level defaults.

Override / escape hatch: every key here is applied with ``setdefault``
semantics — define the same name in your ``settings.py`` before calling
``karni_settings(globals())`` (or pass it as a keyword override, or assign it
after the call) and your value wins. Values marked as environment-driven can
also be changed via the environment variables documented in the README.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import environ

env = environ.Env()
"""Shared environment reader used by every Karni conf module.

Override / escape hatch: set the documented environment variables (usually via
a ``.env`` file loaded by your process manager or docker-compose), or bypass
the environment entirely by assigning the corresponding setting in your
``settings.py``.
"""

INSECURE_SECRET_KEY = "karni-insecure-dev-key"
"""The known-insecure development ``SECRET_KEY`` default.

Validation refuses to start a project with ``DEBUG = False`` while
``SECRET_KEY`` is still this value.
"""

_REDIS_URL: str = env("REDIS_URL", default="redis://redis:6379/0")
_PROJECT_NAME: str = env("PROJECT_NAME", default="karni-project")
_ADMIN_TITLE: str = env("KARNI_ADMIN_TITLE", default=f"{_PROJECT_NAME} admin")

SOCIAL_APPS: tuple[str, ...] = (
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
)
"""Apps appended to ``INSTALLED_APPS`` when ``KARNI_SOCIAL_AUTH`` is enabled.

Provider apps (``allauth.socialaccount.providers.<name>``) are added on top,
one per entry in ``KARNI_SOCIAL_PROVIDERS``.
"""

TWOFA_APPS: tuple[str, ...] = ("django_otp", "django_otp.plugins.otp_totp")
"""Apps appended to ``INSTALLED_APPS`` when ``KARNI_2FA`` is enabled."""

ALLAUTH_MIDDLEWARE = "allauth.account.middleware.AccountMiddleware"
"""Middleware appended when ``KARNI_SOCIAL_AUTH`` is enabled."""

OTP_MIDDLEWARE = "django_otp.middleware.OTPMiddleware"
"""Middleware inserted after ``AuthenticationMiddleware`` when ``KARNI_2FA``
is enabled in session auth mode (JWT mode never installs it)."""

AUTH_THROTTLE_DEFAULTS: dict[str, str | None] = {
    "auth.login": "10/min",
    "auth.login_account": "10/hour",
    "auth.register": "10/hour",
    "auth.password_reset": "5/hour",
    "auth.token": "30/min",
    "auth.verify": "10/hour",
    "auth.email_change": "5/hour",
    "auth.2fa": "10/min",
}
"""Default per-scope throttle rates for the ``karni.accounts`` endpoints.

Override / escape hatch: define ``KARNI_AUTH_THROTTLE_RATES`` (a partial dict
merged over these defaults) in ``settings.py`` before calling
``karni_settings()``, or set the ``KARNI_AUTH_THROTTLE_RATES`` environment
variable to a JSON object. Setting a rate to ``None`` disables throttling for
that scope (standard DRF behaviour).
"""


def _auth_throttle_rates(env: environ.Env) -> dict[str, str | None]:
    """Merge the ``KARNI_AUTH_THROTTLE_RATES`` env JSON over the defaults.

    Override / escape hatch: the same setting can also be defined directly in
    ``settings.py`` (a partial dict is fine — missing scopes keep their
    defaults when ``karni_settings()`` merges the rates into
    ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``).
    """
    overrides: dict[str, str | None] = env.json("KARNI_AUTH_THROTTLE_RATES", default={})
    return {**AUTH_THROTTLE_DEFAULTS, **overrides}


def _storages(env: environ.Env) -> dict[str, dict[str, Any]]:
    """Build the ``STORAGES`` setting from the ``KARNI_STORAGE`` environment variable.

    ``KARNI_STORAGE="s3"`` selects :class:`karni.storage.S3Storage` (an
    S3-compatible backend that also works with MinIO/R2 via
    ``AWS_S3_ENDPOINT_URL``); any other value selects Django's local
    ``FileSystemStorage``. The ``staticfiles`` backend is Django's default.

    Override / escape hatch: define ``STORAGES`` yourself in ``settings.py``
    before calling ``karni_settings()`` to replace the whole mapping.
    """
    if env("KARNI_STORAGE", default="local") == "s3":
        default = {"BACKEND": "karni.storage.S3Storage"}
    else:
        default = {"BACKEND": "django.core.files.storage.FileSystemStorage"}
    return {
        "default": default,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


BASE: dict[str, Any] = {
    # --- Core -------------------------------------------------------------
    "SECRET_KEY": env("SECRET_KEY", default=INSECURE_SECRET_KEY),
    "INSTALLED_APPS": [
        # unfold must precede django.contrib.admin so its templates win;
        # karni_settings() re-inserts it before contrib.admin when merging
        # into a user-supplied INSTALLED_APPS, and validation enforces the
        # ordering either way.
        "unfold",
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        "corsheaders",
        "rest_framework",
        # Installed unconditionally (both auth modes) so switching
        # KARNI_AUTH_MODE never adds or removes migrations.
        "rest_framework_simplejwt.token_blacklist",
        "django_filters",
        "drf_spectacular",
        "django_celery_beat",
        "django_celery_results",
        "django_structlog",
        "karni.accounts",
        "karni",
        # Last on purpose: karni.admin's ready() autodiscovers *unregistered*
        # models, so every explicit registration (project admin.py files,
        # third-party apps) must have happened first.
        "karni.admin",
    ],
    "MIDDLEWARE": [
        "django.middleware.security.SecurityMiddleware",
        "corsheaders.middleware.CorsMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
        "django_structlog.middlewares.RequestMiddleware",
    ],
    "TEMPLATES": [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [],
            "APP_DIRS": True,
            "OPTIONS": {
                "context_processors": [
                    "django.template.context_processors.debug",
                    "django.template.context_processors.request",
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                ],
            },
        },
    ],
    "ROOT_URLCONF": "config.urls",
    "WSGI_APPLICATION": "config.wsgi.application",
    "ASGI_APPLICATION": "config.asgi.application",
    "DEFAULT_AUTO_FIELD": "django.db.models.BigAutoField",
    "TIME_ZONE": "UTC",
    "USE_TZ": True,
    "LANGUAGE_CODE": "en-us",
    "AUTH_PASSWORD_VALIDATORS": [
        {
            "NAME": ("django.contrib.auth.password_validation.UserAttributeSimilarityValidator"),
        },
        {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
        {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
        {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    ],
    # --- Accounts & auth ----------------------------------------------------
    # Swap path: subclass karni.accounts.models.AbstractKarniUser in your app
    # and set AUTH_USER_MODEL = "myapp.User" BEFORE the first migrate.
    "AUTH_USER_MODEL": "karni_accounts.User",
    "KARNI_AUTH_MODE": env("KARNI_AUTH_MODE", default="jwt"),
    "KARNI_2FA": env.bool("KARNI_2FA", default=False),
    "KARNI_SOCIAL_AUTH": env.bool("KARNI_SOCIAL_AUTH", default=False),
    "KARNI_SOCIAL_PROVIDERS": env.list("KARNI_SOCIAL_PROVIDERS", default=[]),
    "KARNI_FRONTEND_URL": env("KARNI_FRONTEND_URL", default="http://localhost:5173"),
    "KARNI_ACCOUNTS_EMAIL_BACKEND": "karni.accounts.emails.DjangoEmailBackend",
    "KARNI_ACCOUNTS_AUTO_LOGIN": False,
    "KARNI_ACCOUNTS_TOKEN_TTL": {
        "verify_email": 86400,
        "reset_password": 3600,
        "change_email": 86400,
    },
    "KARNI_ACCOUNTS_LINKS": {
        "verify_email": "{frontend}/auth/verify-email?token={token}",
        "reset_password": "{frontend}/auth/reset-password?token={token}",
        "change_email": "{frontend}/auth/confirm-email-change?token={token}",
    },
    "KARNI_AUTH_THROTTLE_RATES": _auth_throttle_rates(env),
    "SIMPLE_JWT": {
        "ACCESS_TOKEN_LIFETIME": timedelta(
            minutes=env.int("KARNI_JWT_ACCESS_LIFETIME", default=15)
        ),
        "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("KARNI_JWT_REFRESH_LIFETIME", default=7)),
        "ROTATE_REFRESH_TOKENS": True,
        "BLACKLIST_AFTER_ROTATION": True,
    },
    # --- Database & cache -------------------------------------------------
    "DATABASES": {
        "default": env.db_url("DATABASE_URL", default="postgres://karni:karni@db:5432/karni"),
    },
    "CACHES": {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _REDIS_URL,
        },
    },
    # --- DRF & API schema -------------------------------------------------
    "REST_FRAMEWORK": {
        # Both authenticators in every KARNI_AUTH_MODE: views branch on the
        # mode per request, so the authentication stack never changes shape.
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
            "rest_framework.authentication.SessionAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticatedOrReadOnly",
        ],
        "DEFAULT_PAGINATION_CLASS": "karni.pagination.KarniPageNumberPagination",
        "PAGE_SIZE": env.int("KARNI_PAGE_SIZE", default=50),
        # Search runs last so search-rank ordering survives unless an
        # explicit ?ordering= parameter was given (OrderingFilter is stock).
        "DEFAULT_FILTER_BACKENDS": [
            "karni.api.filters.KarniFilterBackend",
            "rest_framework.filters.OrderingFilter",
            "karni.api.filters.KarniSearchFilter",
        ],
        "DEFAULT_SCHEMA_CLASS": "karni.api.schema.KarniAutoSchema",
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.AnonRateThrottle",
            "rest_framework.throttling.UserRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "anon": env("THROTTLE_ANON", default="100/min"),
            "user": env("THROTTLE_USER", default="1000/min"),
            **_auth_throttle_rates(env),
        },
        # The Karni stack ships one proxy (Caddy) in front of Django; adjust
        # via the KARNI_NUM_PROXIES env var so throttling keys on the real
        # client IP rather than the proxy's.
        "NUM_PROXIES": env.int("KARNI_NUM_PROXIES", default=1),
    },
    "SPECTACULAR_SETTINGS": {
        "TITLE": f"{_PROJECT_NAME} API",
        "VERSION": "0.1.0",
        "SERVE_INCLUDE_SCHEMA": False,
        # Split request/response components so file-upload fields keep their
        # binary format on the request side (frontend codegen relies on it).
        "COMPONENT_SPLIT_REQUEST": True,
        # Keep spectacular's default enum postprocessing, then stamp the root
        # x-karni-auth-mode extension @karni/ui's AuthProvider defaults from.
        "POSTPROCESSING_HOOKS": [
            "drf_spectacular.hooks.postprocess_schema_enums",
            "karni.api.schema.add_auth_mode",
        ],
    },
    # --- Celery (django namespace, read by karni.celery.create_celery_app) -
    "CELERY_BROKER_URL": _REDIS_URL,
    "CELERY_RESULT_BACKEND": "django-db",
    "CELERY_BEAT_SCHEDULER": "django_celery_beat.schedulers:DatabaseScheduler",
    "CELERY_TASK_TIME_LIMIT": 300,
    "CELERY_TASK_SOFT_TIME_LIMIT": 240,
    "CELERY_WORKER_PREFETCH_MULTIPLIER": 1,
    # Daily maintenance: blacklisted/expired JWT rows are flushed by a small
    # karni.accounts task (wraps the flushexpiredtokens management command).
    # Remove or override the "karni-flush-expired-tokens" key to opt out.
    "CELERY_BEAT_SCHEDULE": {
        "karni-flush-expired-tokens": {
            "task": "karni.accounts.tasks.flush_expired_tokens",
            "schedule": timedelta(days=1),
        },
    },
    # --- Files & storage --------------------------------------------------
    "STORAGES": _storages(env),
    "KARNI_STORAGE": env("KARNI_STORAGE", default="local"),
    "AWS_ACCESS_KEY_ID": env("AWS_ACCESS_KEY_ID", default=""),
    "AWS_SECRET_ACCESS_KEY": env("AWS_SECRET_ACCESS_KEY", default=""),
    "AWS_STORAGE_BUCKET_NAME": env("AWS_STORAGE_BUCKET_NAME", default=""),
    "AWS_S3_ENDPOINT_URL": env("AWS_S3_ENDPOINT_URL", default=""),
    "AWS_S3_REGION_NAME": env("AWS_S3_REGION_NAME", default=""),
    "MEDIA_ROOT": env("MEDIA_ROOT", default="/data/media"),
    "MEDIA_URL": "/media/",
    "STATIC_ROOT": env("STATIC_ROOT", default="/data/static"),
    "STATIC_URL": "/static/",
    # --- CORS ---------------------------------------------------------------
    "CORS_ALLOWED_ORIGINS": env.list("CORS_ALLOWED_ORIGINS", default=[]),
    # --- API (karni.api) ----------------------------------------------------
    "KARNI_SEARCH_PROVIDER": env(
        "KARNI_SEARCH_PROVIDER",
        default="karni.api.search.postgres.PostgresSearchProvider",
    ),
    "KARNI_API_MAX_EXPAND_DEPTH": env.int("KARNI_API_MAX_EXPAND_DEPTH", default=2),
    # Zero-argument factory returning the router karni.api.urls exposes;
    # consumed at first URLconf import (overriding it later is a no-op).
    "KARNI_API_ROUTER": env("KARNI_API_ROUTER", default="karni.api.routers.get_default_router"),
    # --- Admin (karni.admin + django-unfold) --------------------------------
    "UNFOLD": {
        "SITE_TITLE": _ADMIN_TITLE,
        "SITE_HEADER": _ADMIN_TITLE,
        "SITE_URL": "/",
        "BORDER_RADIUS": "8px",
        # Neutral indigo-based brand scale (Tailwind indigo); unfold's auto
        # light/dark switcher stays enabled because THEME is left unset.
        "COLORS": {
            "primary": {
                "50": "oklch(0.962 0.018 272.314)",
                "100": "oklch(0.93 0.034 272.788)",
                "200": "oklch(0.87 0.065 274.039)",
                "300": "oklch(0.785 0.115 274.713)",
                "400": "oklch(0.673 0.182 276.935)",
                "500": "oklch(0.585 0.233 277.117)",
                "600": "oklch(0.511 0.262 276.966)",
                "700": "oklch(0.457 0.24 277.023)",
                "800": "oklch(0.398 0.195 277.366)",
                "900": "oklch(0.359 0.144 278.697)",
                "950": "oklch(0.257 0.09 281.288)",
            },
        },
    },
    "KARNI_ADMIN_AUTODISCOVER": env.bool("KARNI_ADMIN_AUTODISCOVER", default=True),
    "KARNI_ADMIN_EXCLUDE": env.list(
        "KARNI_ADMIN_EXCLUDE",
        default=[
            "sessions",
            "contenttypes",
            "admin",
            "auth.Permission",
            "django_celery_results.ChordCounter",
        ],
    ),
    "KARNI_ADMIN_LIST_DISPLAY_MAX": 6,
    "KARNI_ADMIN_LIST_FILTER_MAX": 6,
    "KARNI_ADMIN_SEARCH_MAX": 5,
    "KARNI_ADMIN_SITE": "django.contrib.admin.site",
    "KARNI_ADMIN_BASE": "unfold.admin.ModelAdmin",
    # --- Karni knobs --------------------------------------------------------
    "KARNI_HEALTH_CHECKS": [
        "karni.health.checks.check_database",
        "karni.health.checks.check_cache",
        "karni.health.checks.check_celery",
    ],
    "KARNI_HEALTH_CELERY_TIMEOUT": 1.0,
    "KARNI_THUMBNAILER": "karni.storage.thumbnails.make_thumbnail",
    "KARNI_VALIDATE": True,
    # Architecture-rule configuration (karni.testing); checks fall back to the
    # same defaults when this setting is absent, so non-karni.conf projects work.
    "KARNI_ARCHITECTURE": {
        "skip_apps": [],
        "sql_allowed": ["*/sql/*", "*/migrations/*"],
        "http_allowed": ["*/services/*", "*/providers/*", "*/tests/*", "conftest.py"],
        "dup": {"min_statements": 8, "exclude": ["*/migrations/*"]},
    },
}
"""Profile-independent defaults merged first by ``karni_settings()``.

Override / escape hatch: any key can be replaced by defining it in the
project's settings module before the ``karni_settings()`` call, passing it as
a keyword override, or assigning it after the call.
"""
