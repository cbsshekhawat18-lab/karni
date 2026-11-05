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
_ADMIN_PATH: str = env("KARNI_ADMIN_PATH", default="admin/")
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
    "auth.social": "10/min",
    "auth.otp_send": "10/hour",
    "auth.otp_send_email": "5/hour",
    "auth.otp_verify": "20/min",
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


def _storages(env: environ.Env, choice: str | None = None) -> dict[str, dict[str, Any]]:
    """Build the ``STORAGES`` setting from ``KARNI_STORAGE`` (``choice``, else the environment).

    ``KARNI_STORAGE="s3"`` selects :class:`karni.storage.S3Storage` (an
    S3-compatible backend that also works with MinIO/R2 via
    ``AWS_S3_ENDPOINT_URL``); any other value selects Django's local
    ``FileSystemStorage``. The ``staticfiles`` backend is Django's default.

    Override / escape hatch: define ``STORAGES`` yourself in ``settings.py``
    before calling ``karni_settings()`` to replace the whole mapping.
    ``karni_settings()`` passes a ``KARNI_STORAGE`` defined before the call as ``choice``.
    """
    if (choice or env("KARNI_STORAGE", default="local")) == "s3":
        default = {"BACKEND": "karni.storage.S3Storage"}
    else:
        default = {"BACKEND": "django.core.files.storage.FileSystemStorage"}
    return {
        "default": default,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


def _caches(env: environ.Env, choice: str | None = None) -> dict[str, dict[str, Any]]:
    """Build ``CACHES`` from ``KARNI_CACHE``: ``redis`` (at ``REDIS_URL``) or ``locmem``.

    ``locmem`` is for a host run without Redis (the quickstart): throttle
    counters then live per process, which ``karni.W501`` flags with DEBUG off.

    Override / escape hatch: define ``CACHES`` yourself in ``settings.py``
    before calling ``karni_settings()``. ``karni_settings()`` passes a
    ``KARNI_CACHE`` defined before the call as ``choice``.
    """
    choice = choice or env("KARNI_CACHE", default="redis")
    if choice == "locmem":
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "karni",
            }
        }
    if choice == "redis":
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": _REDIS_URL,
            }
        }
    from karni.exceptions import KarniImproperlyConfigured

    raise KarniImproperlyConfigured(
        f"KARNI_CACHE={choice!r}: use 'redis' (REDIS_URL, the default) or 'locmem'. "
        "Define CACHES yourself for anything else.",
        code="E507",
    )


#: Django's own sender addresses: ``karni check --deploy`` reports them (``karni.W520``).
DJANGO_FROM_EMAIL = "webmaster@localhost"
DJANGO_SERVER_EMAIL = "root@localhost"


def _email(env: environ.Env) -> dict[str, Any]:
    """Django's email settings from the environment.

    ``EMAIL_URL`` names the mail server in django-environ's format, for
    example ``smtp+tls://user:password@smtp.example.com:587`` (``smtps://``
    for SSL, ``consolemail://`` to print each email). It sets
    ``EMAIL_BACKEND``, ``EMAIL_HOST``, ``EMAIL_PORT``, ``EMAIL_HOST_USER``,
    ``EMAIL_HOST_PASSWORD`` and ``EMAIL_USE_TLS`` or ``EMAIL_USE_SSL``.
    Unset, Django's defaults stay (SMTP at localhost, port 25), and the dev
    profile prints mail to the console. ``DEFAULT_FROM_EMAIL`` and
    ``SERVER_EMAIL`` are read too, with Django's defaults, which
    ``karni check --deploy`` reports (``karni.W520``).

    Override / escape hatch: define any ``EMAIL_*`` setting in settings.py,
    before or after ``karni_settings()``.
    """
    found: dict[str, Any] = {
        "DEFAULT_FROM_EMAIL": env("DEFAULT_FROM_EMAIL", default=DJANGO_FROM_EMAIL),
        "SERVER_EMAIL": env("SERVER_EMAIL", default=DJANGO_SERVER_EMAIL),
    }
    url = env.str("EMAIL_URL", default="")
    if url:
        config = environ.Env.email_url_config(url)
        found.update({name: value for name, value in config.items() if value not in (None, "")})
    return found


def _primary_tint(percent: int) -> str:
    """CSS for ``percent`` of @karni/ui's primary over its background (an unfold scale step)."""
    return (
        f"color-mix(in srgb, var(--karni-color-primary) {percent}%, var(--karni-color-background))"
    )


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
        "karni.audit",
        "karni.transfer",
        "karni",
        # Last on purpose: karni.admin's ready() autodiscovers *unregistered*
        # models, so every explicit registration (project admin.py files,
        # third-party apps) must have happened first.
        "karni.admin",
    ],
    "MIDDLEWARE": [
        # First: every log line, task, email and history entry of the request
        # carries its id (X-Request-ID); before django-structlog's middleware.
        "karni.tracing.RequestIdMiddleware",
        # Counts every query of the request; a no-op (removed from the chain
        # at startup) unless KARNI_QUERY_LOG is on (dev profile).
        "karni.middleware.QueryLogMiddleware",
        # .karni/ request records and failure snapshots; removed from the
        # chain at startup unless DEBUG is on (and KARNI_DEBUG_CAPTURE).
        "karni.debug.middleware.CaptureMiddleware",
        "django.middleware.security.SecurityMiddleware",
        # Content-Security-Policy (report-only while DEBUG is on) and
        # Permissions-Policy on every response. KARNI_CSP and friends tune it.
        "karni.security.SecurityHeadersMiddleware",
        "corsheaders.middleware.CorsMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        # Backs AuditedModel.created_by/updated_by; resolves the user lazily,
        # so JWT users authenticated later inside DRF views are seen too.
        "karni.middleware.CurrentUserMiddleware",
        # The terms gate (experimental): 403 E245 under KARNI_TERMS["paths"] until a
        # signed-in user accepts the current version. Removed from the chain at
        # startup unless KARNI_TERMS requires acceptance. After authentication.
        "karni.accounts.terms.TermsGateMiddleware",
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
    # Empty, so a project extends it: SILENCED_SYSTEM_CHECKS += ["karni.W967"].
    "SILENCED_SYSTEM_CHECKS": [],
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
    # Sign-in with a Google, Microsoft or Apple ID token (experimental), in both
    # auth modes and independent of KARNI_SOCIAL_AUTH: {name: {"client_ids": [...]}}.
    # Each configured name mounts social/<name>/. Needs karni[social-token].
    "KARNI_SOCIAL_TOKEN_PROVIDERS": env.json("KARNI_SOCIAL_TOKEN_PROVIDERS", default={}),
    # Who a token without an account may become: "open", "approval" or "existing".
    # None follows KARNI_ACCOUNTS_REGISTRATION ("open" while it is on, else "existing").
    "KARNI_SOCIAL_TOKEN_SIGNUP": env("KARNI_SOCIAL_TOKEN_SIGNUP", default=None),
    # Link a token to an existing account with its email (only a provider-verified one).
    "KARNI_SOCIAL_TOKEN_LINK_VERIFIED": env.bool("KARNI_SOCIAL_TOKEN_LINK_VERIFIED", default=True),
    # Seconds of clock skew allowed on exp, iat and nbf.
    "KARNI_SOCIAL_TOKEN_LEEWAY": env.int("KARNI_SOCIAL_TOKEN_LEEWAY", default=60),
    # Seconds a provider's key set (JWKS) stays in the default cache.
    "KARNI_SOCIAL_TOKEN_JWKS_TTL": env.int("KARNI_SOCIAL_TOKEN_JWKS_TTL", default=21600),
    # Dotted path of the function that fetches a key set: (url) -> dict.
    "KARNI_SOCIAL_TOKEN_JWKS_FETCHER": "karni.accounts.social_token.fetch_jwks",
    # Sign-in with a code sent by email (experimental), in both auth modes: mounts
    # otp/send/ and otp/verify/ while True. The code goes through the accounts email backend.
    "KARNI_EMAIL_OTP": env.bool("KARNI_EMAIL_OTP", default=False),
    # Seconds a code lives (60 to 3600).
    "KARNI_EMAIL_OTP_TTL": env.int("KARNI_EMAIL_OTP_TTL", default=600),
    # Digits in a code (4 to 10).
    "KARNI_EMAIL_OTP_LENGTH": env.int("KARNI_EMAIL_OTP_LENGTH", default=6),
    # Guesses a code takes before it dies (1 to 10).
    "KARNI_EMAIL_OTP_MAX_ATTEMPTS": env.int("KARNI_EMAIL_OTP_MAX_ATTEMPTS", default=5),
    # Who an address without an account may become: "open", "approval" or "existing".
    # None follows KARNI_ACCOUNTS_REGISTRATION ("open" while it is on, else "existing").
    "KARNI_EMAIL_OTP_SIGNUP": env("KARNI_EMAIL_OTP_SIGNUP", default=None),
    # A versioned terms (EULA) acceptance gate (experimental): {"version": "2026-11",
    # "url": "/terms/", "required": True}, plus "paths" (default ["/api/"]) and "exempt".
    # Set, it mounts terms/ and terms/accept/. None (the default) gates nothing.
    "KARNI_TERMS": env.json("KARNI_TERMS", default=None),
    "KARNI_FRONTEND_URL": env("KARNI_FRONTEND_URL", default="http://localhost:5173"),
    "KARNI_ACCOUNTS_EMAIL_BACKEND": "karni.accounts.emails.DjangoEmailBackend",
    "KARNI_ACCOUNTS_AUTO_LOGIN": False,
    # Whether anyone may open an account through register/. False leaves the
    # route out (404) and out of the OpenAPI schema: staff create accounts.
    "KARNI_ACCOUNTS_REGISTRATION": env.bool("KARNI_ACCOUNTS_REGISTRATION", default=True),
    # Roles (Django groups) every self-registered user starts with, e.g. ["attendee"].
    "KARNI_ACCOUNTS_DEFAULT_ROLES": env.list("KARNI_ACCOUNTS_DEFAULT_ROLES", default=[]),
    # A form field no person fills in; a registration that fills it is a bot
    # and is accepted without creating anything. "" turns the honeypot off.
    "KARNI_ACCOUNTS_HONEYPOT_FIELD": env("KARNI_ACCOUNTS_HONEYPOT_FIELD", default="website"),
    # The project's roles and what they may do: slug -> {name, description, system,
    # grants: {"app.model:action" pattern: scope}}; see docs/accounts.md#roles.
    # Reconciled into the role tables by `karni sync-roles` (and after migrate).
    "KARNI_ROLES": {
        "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
        "user": {"name": "User", "grants": {"*": "own"}},
        "customer": {"name": "Customer", "grants": {"*": "own"}},
    },
    "KARNI_ROLES_AUTOSYNC": env.bool("KARNI_ROLES_AUTOSYNC", default=True),
    # Per-user grants (experimental): while True, each user's UserGrant rows join their
    # role grants (one more query per request). Off, they grant nothing and cost nothing.
    "KARNI_USER_GRANTS": env.bool("KARNI_USER_GRANTS", default=False),
    # Navigation from data (experimental): a list of menu items and groups, "db" (the
    # NavItem table of the karni.navigation app) or None (no menu, no navigation/ route).
    "KARNI_NAVIGATION": None,
    # The frontend files whose `path:` entries are the app's pages: karni check reports
    # a menu item whose route none of them serves. [] turns that comparison off.
    "KARNI_NAVIGATION_PAGES": ["frontend/src/routes.tsx"],
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
    # Experimental: class Karni: database = "<alias>" sends a model to another alias. A
    # project's own routers go before this one (karni_settings() appends it after them).
    "DATABASE_ROUTERS": ["karni.db.DatabaseRouter"],
    # "redis" (the default cache at REDIS_URL) or "locmem" (a host run without Redis).
    "KARNI_CACHE": env("KARNI_CACHE", default="redis"),
    "CACHES": _caches(env),
    # --- Email ----------------------------------------------------------------
    # EMAIL_URL (smtp+tls://user:password@host:587), DEFAULT_FROM_EMAIL, SERVER_EMAIL.
    **_email(env),
    # Django's default sends a direct /admin/login/ to /accounts/profile/ (a 404).
    "LOGIN_REDIRECT_URL": f"/{_ADMIN_PATH}",
    # --- DRF & API schema -------------------------------------------------
    "REST_FRAMEWORK": {
        # Both authenticators in every KARNI_AUTH_MODE: views branch on the
        # mode per request, so the authentication stack never changes shape.
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
            "rest_framework.authentication.SessionAuthentication",
        ],
        # Not the gate of a BaseViewSet: its `access` declaration is (ADR 0001
        # Q2.1). This fallback covers plain DRF views and Unscoped viewsets only.
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
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
        # spectacular's enum postprocessing, with colliding enums named by
        # model and field (BookingStatusEnum, not Status469Enum), then the root
        # x-karni-auth-mode extension @karni/ui's AuthProvider defaults from.
        # ENUM_NAME_OVERRIDES still wins over Karni's enum names.
        "POSTPROCESSING_HOOKS": [
            "karni.api.schema.postprocess_schema_enums",
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
    # Django's two finders, then the one that serves the project's
    # karni-theme.css to the admin as karni/project-theme.css (karni.admin.theme).
    "STATICFILES_FINDERS": [
        "django.contrib.staticfiles.finders.FileSystemFinder",
        "django.contrib.staticfiles.finders.AppDirectoriesFinder",
        "karni.admin.theme.ProjectThemeFinder",
    ],
    # --- CORS and CSRF ------------------------------------------------------
    "CORS_ALLOWED_ORIGINS": env.list("CORS_ALLOWED_ORIGINS", default=[]),
    # The https origins of the site for Django's CSRF check, e.g.
    # https://example.com. Session mode adds KARNI_FRONTEND_URL's origin.
    "CSRF_TRUSTED_ORIGINS": env.list("CSRF_TRUSTED_ORIGINS", default=[]),
    # --- API (karni.api) ----------------------------------------------------
    "KARNI_SEARCH_PROVIDER": env(
        "KARNI_SEARCH_PROVIDER",
        default="karni.api.search.postgres.PostgresSearchProvider",
    ),
    "KARNI_API_MAX_EXPAND_DEPTH": env.int("KARNI_API_MAX_EXPAND_DEPTH", default=2),
    # Cross-model search, GET /api/search/ (karni.global_search, experimental).
    "KARNI_GLOBAL_SEARCH_MIN_LENGTH": env.int("KARNI_GLOBAL_SEARCH_MIN_LENGTH", default=2),
    "KARNI_GLOBAL_SEARCH_LIMIT": env.int("KARNI_GLOBAL_SEARCH_LIMIT", default=5),
    "KARNI_GLOBAL_SEARCH_MAX_LIMIT": env.int("KARNI_GLOBAL_SEARCH_MAX_LIMIT", default=20),
    "KARNI_GLOBAL_SEARCH_THRESHOLD": env.float("KARNI_GLOBAL_SEARCH_THRESHOLD", default=0.3),
    # Zero-argument factory returning the router karni.api.urls exposes;
    # consumed at first URLconf import (overriding it later is a no-op).
    "KARNI_API_ROUTER": env("KARNI_API_ROUTER", default="karni.api.routers.get_default_router"),
    # The limit on each caller of a create anyone may call (create=Public()),
    # unless the viewset declares throttle = Throttle(create=...). "" or None: off.
    "KARNI_PUBLIC_CREATE_RATE": env("KARNI_PUBLIC_CREATE_RATE", default="10/hour"),
    # A hidden form field on such a create. A request that fills it is a
    # script and is accepted without saving anything. "" turns it off.
    "KARNI_PUBLIC_CREATE_HONEYPOT_FIELD": env(
        "KARNI_PUBLIC_CREATE_HONEYPOT_FIELD", default="homepage"
    ),
    # --- Performance (ADR 0001 Decision 3) ----------------------------------
    # Hard cap on ?page_size= for every Karni paginator; it may not be set
    # below the floor (25 = @karni/ui ResourceTable's page size; never < 1).
    "KARNI_MAX_PAGE_SIZE": env.int("KARNI_MAX_PAGE_SIZE", default=100),
    "KARNI_MAX_PAGE_SIZE_FLOOR": env.int("KARNI_MAX_PAGE_SIZE_FLOOR", default=25),
    # Queries allowed per BaseViewSet action ("*" = any other action); a
    # partial dict is merged over these. Per viewset: query_budget = Budget(...).
    "KARNI_QUERY_BUDGET": {
        "list": 8,
        "retrieve": 8,
        "create": 12,
        "update": 12,
        "partial_update": 12,
        "destroy": 10,
        "*": 15,
    },
    # raise (tests: set by the karni pytest plugin) | warn (dev) | off (prod).
    "KARNI_QUERY_BUDGET_MODE": env("KARNI_QUERY_BUDGET_MODE", default="off"),
    # Per-request query count / duplicates / time log (QueryLogMiddleware).
    "KARNI_QUERY_LOG": env.bool("KARNI_QUERY_LOG", default=False),
    # Extra `karni seed` logins with their roles, e.g. {"organizer@example.com": ["organizer"]}.
    "KARNI_SEED_LOGINS": env.json("KARNI_SEED_LOGINS", default={}),
    # Response caching for BaseViewSet list/retrieve (karni.api.caching).
    "KARNI_API_CACHE": env.bool("KARNI_API_CACHE", default=False),
    "KARNI_API_CACHE_TTL": env.int("KARNI_API_CACHE_TTL", default=300),
    "KARNI_API_CACHE_ALIAS": env("KARNI_API_CACHE_ALIAS", default="default"),
    # The most groups one GET <resource>/aggregate/ returns (karni.aggregation, experimental).
    "KARNI_AGGREGATE_MAX_GROUPS": env.int("KARNI_AGGREGATE_MAX_GROUPS", default=1000),
    # A daily full flush through Celery beat: "03:30" or "03:30 Europe/Paris". Off by default.
    "KARNI_API_CACHE_FLUSH": env("KARNI_API_CACHE_FLUSH", default=None),
    # Transitional until 1.0: also send the deprecated X-Karni-Cache header (X-Cache replaces it).
    "KARNI_API_CACHE_LEGACY_HEADER": env.bool("KARNI_API_CACHE_LEGACY_HEADER", default=True),
    # --- Admin (karni.admin + django-unfold) --------------------------------
    "UNFOLD": {
        "SITE_TITLE": _ADMIN_TITLE,
        "SITE_HEADER": _ADMIN_TITLE,
        "SITE_URL": "/",
        # The admin wears @karni/ui's brand (see karni.admin.theme): the token
        # stylesheet and the unfold bridge load first, and the colours below
        # read the tokens, so they follow the light/dark theme and a project's
        # token overrides. THEME comes from KARNI_ADMIN_THEME (light by
        # default, so the light/dark/system switch is hidden): karni_settings()
        # wires it in, see karni.conf.admin_theme.
        "BORDER_RADIUS": "var(--karni-radius-md)",
        "STYLES": [
            "karni.admin.theme.tokens_stylesheet",
            "karni.admin.theme.unfold_theme_stylesheet",
            # The project's karni-theme.css (KARNI_THEME_CSS), the file its
            # staff app loads: one set of brand tokens for both.
            "karni.admin.theme.project_theme_stylesheet",
        ],
        "COLORS": {
            # Unfold steps through this neutral scale itself (base-200 borders
            # in light, base-800 in dark), so it holds fixed values: the
            # Tailwind gray the tokens are drawn from, with each step the
            # tokens use written exactly as tokens.css writes it (a test pins
            # them): 900 is the dark background, 800 the dark border.
            "base": {
                "50": "hsl(210 20% 98%)",
                "100": "hsl(220 14.3% 95.9%)",
                "200": "hsl(220 13% 91%)",
                "300": "hsl(216 12.2% 83.9%)",
                "400": "hsl(217.9 10.6% 64.9%)",
                "500": "hsl(220 8.9% 43%)",
                "600": "hsl(215 13.8% 34.1%)",
                "700": "hsl(216.9 19.1% 26.7%)",
                "800": "hsl(215 27.9% 16.9%)",
                "900": "hsl(224 71.4% 4.1%)",
                "950": "hsl(224 71.4% 4.1%)",
            },
            # @karni/ui's primary in both themes: unfold fills buttons with
            # 600 and colours dark-mode links with 500, so 500-800 are the
            # primary itself; lighter steps are tints toward the background,
            # 900 (the bulk-action button on the primary bar) a step off it.
            "primary": {
                "50": _primary_tint(4),
                "100": _primary_tint(8),
                "200": _primary_tint(16),
                "300": _primary_tint(32),
                "400": _primary_tint(64),
                "500": "var(--karni-color-primary)",
                "600": "var(--karni-color-primary)",
                "700": "var(--karni-color-primary)",
                "800": "var(--karni-color-primary)",
                "900": _primary_tint(80),
                "950": _primary_tint(80),
            },
            "font": {
                "subtle-light": "var(--karni-color-muted-foreground)",
                "subtle-dark": "var(--karni-color-muted-foreground)",
                "default-light": "var(--color-base-600)",
                "default-dark": "var(--color-base-300)",
                "important-light": "var(--karni-color-foreground)",
                "important-dark": "var(--karni-color-foreground)",
            },
        },
    },
    "KARNI_ADMIN_AUTODISCOVER": env.bool("KARNI_ADMIN_AUTODISCOVER", default=True),
    # A role's grant opens the admin page for that model and action (rows still
    # follow the grant's scope). False: only Django's model permissions open
    # pages, as in 0.4.0 (karni.admin.base.KarniAdminMixin.granted).
    "KARNI_ADMIN_GRANTS_OPEN_PAGES": env.bool("KARNI_ADMIN_GRANTS_OPEN_PAGES", default=True),
    # The admin's colour scheme: "light" (the default: light only, no switch),
    # "dark", or "auto" (unfold's light/dark/system switch). Wired into
    # UNFOLD["THEME"] by karni_settings(), read per request.
    "KARNI_ADMIN_THEME": env("KARNI_ADMIN_THEME", default="light"),
    # <meta name="generator"> on Karni's public pages ({% karni_seo %}), so tools
    # that list a site's technologies see Karni. No version on purpose. "" turns it off.
    "KARNI_GENERATOR": env("KARNI_GENERATOR", default="Karni"),
    # Logo for the admin header and login screen: "" (none, the default),
    # "karni" (Karni's own mark) or {"light": <static path>, "dark": ..., "icon": ...}.
    # Wired into UNFOLD by karni_settings(); see docs/admin.md#theming.
    "KARNI_ADMIN_LOGO": env("KARNI_ADMIN_LOGO", default="") or None,
    # The project's brand tokens, the file `karni ui detect` writes for the
    # staff app; the admin loads it too (karni.admin.theme). "" for none.
    "KARNI_THEME_CSS": env("KARNI_THEME_CSS", default="frontend/src/karni-theme.css"),
    # Where the scaffold mounts the Django admin; a path nobody guesses keeps
    # the login form out of scanners' lists. Trailing slash required.
    "KARNI_ADMIN_PATH": env("KARNI_ADMIN_PATH", default="admin/"),
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
    # Apps or models the permission matrix leaves out: framework internals
    # nobody grants by role (kept in sync with karni.accounts.matrix).
    "KARNI_MATRIX_EXCLUDE": env.list(
        "KARNI_MATRIX_EXCLUDE",
        default=[
            "admin",
            "auth",
            "contenttypes",
            "sessions",
            "sites",
            "django_celery_beat",
            "django_celery_results",
            "token_blacklist",
            "django_otp",
            "otp_totp",
            "otp_static",
            "account",
            "socialaccount",
            "karni_audit",
            "karni_transfer",
            "karni_accounts.OneTimeToken",
            "karni_accounts.Permission",
            "karni_accounts.SocialIdentity",
            "karni_accounts.LoginCode",
        ],
    ),
    # --- Security headers (karni.security) ----------------------------------
    # Directives merged into Karni's Content-Security-Policy, e.g.
    # {"font-src": ["https://fonts.gstatic.com"]}. None: no CSP header at all.
    "KARNI_CSP": env.json("KARNI_CSP", default={}),
    # True sends the policy as Content-Security-Policy-Report-Only, False
    # enforces it. None (the default) follows DEBUG: report-only in development.
    "KARNI_CSP_REPORT_ONLY": env.bool("KARNI_CSP_REPORT_ONLY", default=None),
    # Browser features merged into Karni's Permissions-Policy, e.g.
    # {"geolocation": ["self"]}. None: no Permissions-Policy header.
    "KARNI_PERMISSIONS_POLICY": env.json("KARNI_PERMISSIONS_POLICY", default={}),
    # --- Karni knobs --------------------------------------------------------
    # Comma-separated in the environment: a deployment without a Celery worker
    # leaves check_celery out, so /health/ready/ does not wait for one.
    "KARNI_HEALTH_CHECKS": env.list(
        "KARNI_HEALTH_CHECKS",
        default=[
            "karni.health.checks.check_database",
            "karni.health.checks.check_cache",
            "karni.health.checks.check_celery",
        ],
    ),
    "KARNI_HEALTH_CELERY_TIMEOUT": 1.0,
    "KARNI_THUMBNAILER": "karni.storage.thumbnails.make_thumbnail",
    "KARNI_VALIDATE": True,
    # PhoneField (karni.fields): the country code a national number gets ("44"),
    # None for international numbers only; the trunk prefix it loses; and the
    # function that does it, read on every call.
    "KARNI_PHONE_COUNTRY_CODE": env("KARNI_PHONE_COUNTRY_CODE", default=None),
    "KARNI_PHONE_TRUNK_PREFIX": env("KARNI_PHONE_TRUNK_PREFIX", default="0"),
    "KARNI_PHONE_NORMALIZER": "karni.fields.text.default_phone_normalizer",
    # --- Import and export (karni.transfer) ---------------------------------
    # Files with at most this many rows import inside the request; larger
    # ones run in Celery with progress. The two caps refuse outright.
    "KARNI_IMPORT_INLINE_ROWS": env.int("KARNI_IMPORT_INLINE_ROWS", default=500),
    "KARNI_IMPORT_MAX_ROWS": env.int("KARNI_IMPORT_MAX_ROWS", default=100_000),
    "KARNI_EXPORT_MAX_ROWS": env.int("KARNI_EXPORT_MAX_ROWS", default=100_000),
    # --- Change history (karni.audit) -------------------------------------
    "KARNI_AUDIT_ASYNC": env.bool("KARNI_AUDIT_ASYNC", default=False),
    "KARNI_AUDIT_RETENTION_DAYS": env.int("KARNI_AUDIT_RETENTION_DAYS", default=None),
    "KARNI_AUDIT_REDACT": env.list(
        "KARNI_AUDIT_REDACT", default=["password", "token", "secret", "key"]
    ),
    # --- Request ids and development capture (karni.tracing / karni.debug) --
    # Accept a client's X-Request-ID with DEBUG off only when the proxy in
    # front overwrites it (and NUM_PROXIES says there is one).
    "KARNI_REQUEST_ID_TRUST_HEADER": env.bool("KARNI_REQUEST_ID_TRUST_HEADER", default=False),
    # Stamp X-Karni-Request-ID on outgoing email (wraps EmailMessage.send).
    "KARNI_REQUEST_ID_EMAILS": True,
    # DEBUG only: request records, failure snapshots and the trace under .karni/.
    "KARNI_DEBUG_CAPTURE": env.bool("KARNI_DEBUG_CAPTURE", default=True),
    "KARNI_DEBUG_CAPTURE_KEEP": env.int("KARNI_DEBUG_CAPTURE_KEEP", default=200),
    "KARNI_DEBUG_TRACE_DAYS": env.int("KARNI_DEBUG_TRACE_DAYS", default=7),
    # --- Events & schedules (karni.events / karni.schedule) -----------------
    # <app>/listeners.py, <app>/events.py and <app>/schedules.py are
    # autodiscovered at startup; set False to wire them yourself.
    "KARNI_EVENTS_AUTODISCOVER": env.bool("KARNI_EVENTS_AUTODISCOVER", default=True),
    "KARNI_SCHEDULES_AUTODISCOVER": env.bool("KARNI_SCHEDULES_AUTODISCOVER", default=True),
    # The key type `karni make model` writes (experimental): "uuid" (BaseModel) or
    # "bigint" (BigIntBaseModel). Read by the CLI from config/settings.py, nothing
    # else: each model's class line decides its key.
    "KARNI_PK": "uuid",
    # Architecture-rule configuration (karni.testing); checks fall back to the
    # same defaults when this setting is absent, so non-karni.conf projects work.
    "KARNI_ARCHITECTURE": {
        "skip_apps": [],
        "sql_allowed": ["*/sql/*", "*/migrations/*"],
        "http_allowed": ["*/services/*", "*/providers/*", "*/tests/*", "conftest.py"],
        "dup": {"min_statements": 8, "exclude": ["*/migrations/*"]},
    },
    # Tooling for large projects (experimental). karni check's cache of per-file
    # results (.karni/local/check-cache.json): False turns it off, a path moves it.
    "KARNI_CHECK_CACHE": True,
    # The rows the scaling check compares, small then large (query_scaling overrides).
    "KARNI_SCALING_ROWS": [2, 12],
    # Rows per model from which karni seed inserts in bulk, and rows per bulk insert.
    "KARNI_SEED_BULK_THRESHOLD": 1000,
    "KARNI_SEED_BATCH_SIZE": 2000,
    # The row counts each seed run leaves (.karni/local/seeded.json): False turns it off.
    "KARNI_SEED_LEDGER": True,
    # karni queries --explain flags sequential scans on tables of this many rows or more.
    "KARNI_EXPLAIN_SEQ_SCAN_ROWS": 1000,
}
"""Profile-independent defaults merged first by ``karni_settings()``.

Override / escape hatch: any key can be replaced by defining it in the
project's settings module before the ``karni_settings()`` call, passing it as
a keyword override, or assigning it after the call.
"""
