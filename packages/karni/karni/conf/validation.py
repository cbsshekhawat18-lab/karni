"""Startup validation of the merged Karni settings.

A Pydantic v2 model checks the values that most often break deployments
(secret key, hosts, database, Redis URLs, storage selection, throttle rates,
pagination that cannot be switched off, query budgets and API caching, auth
mode and social/2FA extras, sign-in with an ID token or a code, terms
acceptance, API knobs, admin app ordering, health-check configuration) and
:func:`validate_settings` turns any problem into a single
``ImproperlyConfigured`` error listing *every* failure, so a bad container
config dies loudly at startup instead of at 3 a.m.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from karni.conf.base import INSECURE_SECRET_KEY
from karni.exceptions import KarniImproperlyConfigured

THROTTLE_RATE_RE = re.compile(r"^\d+/(s|sec|second|m|min|minute|h|hour|d|day)$")
"""Accepted DRF throttle-rate format, e.g. ``"100/min"`` or ``"5/second"``."""

_REDIS_SCHEMES = frozenset({"redis", "rediss", "unix"})
_VALID_STORAGES = frozenset({"local", "s3"})
_VALID_AUTH_MODES = frozenset({"jwt", "session"})
_FRONTEND_SCHEMES = frozenset({"http", "https"})
_BUDGET_MODES = ("raise", "warn", "off")  # karni.performance.BUDGET_MODES (import-light here)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _importable(module: str) -> bool:
    """Return whether ``module`` can be found without importing it."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


class KarniSettingsModel(BaseModel):
    """Pydantic v2 model validating the merged Django settings.

    Unknown settings are ignored, so projects can add anything they like;
    only the fields declared here are checked.

    Override / escape hatch: set ``KARNI_VALIDATE = False`` in your settings
    to skip validation at startup, or subclass this model and call
    ``YourModel.model_validate(...)`` from your own ``AppConfig.ready()`` for
    stricter project-specific rules.
    """

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    DEBUG: bool = False
    SECRET_KEY: str = ""
    ALLOWED_HOSTS: list[str] = Field(default_factory=list)
    INSTALLED_APPS: list[Any] = Field(default_factory=list)
    DATABASES: dict[str, Any] = Field(default_factory=dict)
    CACHES: dict[str, Any] = Field(default_factory=dict)
    REST_FRAMEWORK: dict[str, Any] = Field(default_factory=dict)
    CELERY_BROKER_URL: str = ""
    KARNI_STORAGE: str = "local"
    KARNI_CACHE: str = "redis"
    AWS_STORAGE_BUCKET_NAME: str = ""
    KARNI_AUTH_MODE: str = "jwt"
    KARNI_SOCIAL_AUTH: bool = False
    KARNI_2FA: bool = False
    KARNI_FRONTEND_URL: str = "http://localhost:5173"
    KARNI_ACCOUNTS_TOKEN_TTL: dict[str, Any] = Field(default_factory=dict)
    KARNI_ACCOUNTS_REGISTRATION: bool = True
    KARNI_ACCOUNTS_DEFAULT_ROLES: list[str] = Field(default_factory=list)
    KARNI_ROLES: dict[str, dict[str, Any]] = Field(default_factory=dict)
    KARNI_ROLES_AUTOSYNC: bool = True
    KARNI_SEED_LOGINS: dict[str, list[str]] = Field(default_factory=dict)
    KARNI_AUTH_THROTTLE_RATES: dict[str, Any] = Field(default_factory=dict)
    KARNI_API_MAX_EXPAND_DEPTH: int = 2
    KARNI_SEARCH_PROVIDER: str = "karni.api.search.postgres.PostgresSearchProvider"
    KARNI_API_ROUTER: str = "karni.api.routers.get_default_router"
    KARNI_MAX_PAGE_SIZE: Any = 100
    KARNI_MAX_PAGE_SIZE_FLOOR: Any = 25
    KARNI_QUERY_BUDGET: Any = Field(default_factory=dict)
    KARNI_QUERY_BUDGET_MODE: Any = "off"
    KARNI_API_CACHE: bool = False
    KARNI_API_CACHE_TTL: Any = 300
    KARNI_API_CACHE_ALIAS: Any = "default"
    KARNI_EVENTS_AUTODISCOVER: bool = True
    KARNI_SCHEDULES_AUTODISCOVER: bool = True
    KARNI_ADMIN_EXCLUDE: list[Any] = Field(default_factory=list)
    KARNI_MATRIX_EXCLUDE: list[Any] = Field(default_factory=list)
    KARNI_IMPORT_INLINE_ROWS: int = Field(default=500, ge=0)
    KARNI_IMPORT_MAX_ROWS: int = Field(default=100_000, ge=1)
    KARNI_EXPORT_MAX_ROWS: int = Field(default=100_000, ge=1)
    KARNI_ADMIN_LOGO: Any = None
    KARNI_ADMIN_THEME: Literal["light", "dark", "auto"] = "light"
    KARNI_THEME_CSS: str | None = "frontend/src/karni-theme.css"
    KARNI_ADMIN_PATH: str = "admin/"
    KARNI_ACCOUNTS_HONEYPOT_FIELD: str = "website"
    KARNI_PUBLIC_CREATE_RATE: str | None = "10/hour"
    KARNI_PUBLIC_CREATE_HONEYPOT_FIELD: str = "homepage"
    KARNI_CSP: Any = Field(default_factory=dict)
    KARNI_CSP_REPORT_ONLY: bool | None = None
    KARNI_PERMISSIONS_POLICY: Any = Field(default_factory=dict)
    KARNI_ADMIN_LIST_DISPLAY_MAX: int = 6
    KARNI_ADMIN_LIST_FILTER_MAX: int = 6
    KARNI_ADMIN_SEARCH_MAX: int = 5
    KARNI_HEALTH_CHECKS: list[str] = Field(default_factory=list)
    KARNI_HEALTH_CELERY_TIMEOUT: float = 1.0
    KARNI_THUMBNAILER: str = "karni.storage.thumbnails.make_thumbnail"
    KARNI_AUDIT_ASYNC: bool = False
    KARNI_AUDIT_RETENTION_DAYS: int | None = None
    KARNI_AUDIT_REDACT: list[str] = Field(default_factory=list)
    KARNI_REQUEST_ID_TRUST_HEADER: bool = False
    KARNI_REQUEST_ID_EMAILS: bool = True
    KARNI_DEBUG_CAPTURE: bool = True
    KARNI_DEBUG_CAPTURE_KEEP: int = Field(default=200, ge=1)
    KARNI_DEBUG_TRACE_DAYS: int = Field(default=7, ge=1)
    KARNI_SOCIAL_TOKEN_PROVIDERS: Any = Field(default_factory=dict)
    KARNI_SOCIAL_TOKEN_SIGNUP: Any = None
    KARNI_SOCIAL_TOKEN_LINK_VERIFIED: Any = True
    KARNI_SOCIAL_TOKEN_LEEWAY: Any = 60
    KARNI_SOCIAL_TOKEN_JWKS_TTL: Any = 21600
    KARNI_SOCIAL_TOKEN_JWKS_FETCHER: Any = "karni.accounts.social_token.fetch_jwks"
    KARNI_EMAIL_OTP: Any = False
    KARNI_EMAIL_OTP_TTL: Any = 600
    KARNI_EMAIL_OTP_LENGTH: Any = 6
    KARNI_EMAIL_OTP_MAX_ATTEMPTS: Any = 5
    KARNI_EMAIL_OTP_SIGNUP: Any = None
    KARNI_TERMS: Any = None
    KARNI_USER_GRANTS: Any = False
    KARNI_NAVIGATION: Any = None
    KARNI_NAVIGATION_PAGES: Any = Field(default_factory=lambda: ["frontend/src/routes.tsx"])
    KARNI_PK: Any = "uuid"

    @model_validator(mode="after")
    def _cross_field_checks(self) -> KarniSettingsModel:
        """Run every cross-field check and raise one error listing all failures."""
        errors = self.cross_field_errors()
        if errors:
            raise ValueError("\n".join(errors))  # karni: bare-raise-ok (pydantic validator)
        return self

    def cross_field_errors(self) -> list[str]:
        """Return every cross-field configuration problem as a human-readable list."""
        errors: list[str] = []
        errors.extend(self._check_secret_key())
        errors.extend(self._check_allowed_hosts())
        errors.extend(self._check_databases())
        errors.extend(self._check_caches())
        errors.extend(self._check_celery_broker())
        errors.extend(self._check_storage())
        errors.extend(self._check_rest_framework())
        errors.extend(self._check_pagination())
        errors.extend(self._check_performance())
        errors.extend(self._check_accounts())
        errors.extend(self._check_social_token())
        errors.extend(self._check_email_otp())
        errors.extend(self._check_terms())
        errors.extend(self._check_user_grants())
        errors.extend(self._check_navigation())
        errors.extend(self._check_pk())
        errors.extend(self._check_api())
        errors.extend(self._check_admin())
        errors.extend(self._check_karni_knobs())
        errors.extend(self._check_security_headers())
        return errors

    def _check_secret_key(self) -> list[str]:
        if not self.SECRET_KEY.strip():
            return ["SECRET_KEY must not be empty"]
        if not self.DEBUG and self.SECRET_KEY == INSECURE_SECRET_KEY:
            return [
                "SECRET_KEY is the insecure Karni dev default. Set a real "
                "SECRET_KEY environment variable when DEBUG is False"
            ]
        return []

    def _check_allowed_hosts(self) -> list[str]:
        if not self.DEBUG and not self.ALLOWED_HOSTS:
            return [
                "ALLOWED_HOSTS must not be empty when DEBUG is False. Set the "
                "ALLOWED_HOSTS environment variable (comma-separated)"
            ]
        return []

    def _check_databases(self) -> list[str]:
        default = self.DATABASES.get("default")
        if not isinstance(default, Mapping) or not default.get("ENGINE"):
            return [
                "DATABASES must define a 'default' connection with an ENGINE. "
                "Set DATABASE_URL or override DATABASES in settings.py"
            ]
        return []

    def _check_caches(self) -> list[str]:
        errors: list[str] = []
        default = self.CACHES.get("default")
        if not isinstance(default, Mapping):
            return ["CACHES must define a 'default' cache"]
        backend = str(default.get("BACKEND", ""))
        if backend.endswith("RedisCache"):
            location = default.get("LOCATION", "")
            locations = location if isinstance(location, list | tuple) else [location]
            for loc in locations:
                scheme = urlsplit(str(loc)).scheme
                if scheme not in _REDIS_SCHEMES:
                    errors.append(
                        f"CACHES['default']['LOCATION'] {loc!r} is not a Redis URL "
                        "(expected scheme redis://, rediss:// or unix://). Check REDIS_URL"
                    )
        return errors

    def _check_celery_broker(self) -> list[str]:
        if not self.CELERY_BROKER_URL:
            return []
        scheme = urlsplit(self.CELERY_BROKER_URL).scheme
        if not scheme:
            return [
                f"CELERY_BROKER_URL {self.CELERY_BROKER_URL!r} is not a URL "
                "(expected e.g. redis://redis:6379/0). Check REDIS_URL"
            ]
        return []

    def _check_storage(self) -> list[str]:
        errors: list[str] = []
        if self.KARNI_STORAGE not in _VALID_STORAGES:
            errors.append(
                f"KARNI_STORAGE {self.KARNI_STORAGE!r} is invalid (expected 'local' or 's3')"
            )
        elif self.KARNI_STORAGE == "s3" and not self.AWS_STORAGE_BUCKET_NAME:
            errors.append("KARNI_STORAGE='s3' requires AWS_STORAGE_BUCKET_NAME to be set")
        return errors

    def _check_rest_framework(self) -> list[str]:
        errors: list[str] = []
        rates = self.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES")
        if isinstance(rates, Mapping):
            for scope, rate in rates.items():
                if rate is None:  # DRF: None disables throttling for the scope
                    continue
                if not isinstance(rate, str) or not THROTTLE_RATE_RE.match(rate):
                    errors.append(
                        f"REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'][{scope!r}] = {rate!r} "
                        "is not a valid throttle rate (expected '<number>/<period>', "
                        "e.g. '100/min'). Check THROTTLE_ANON / THROTTLE_USER"
                    )
        return errors

    def _check_pagination(self) -> list[str]:
        """Pagination cannot be switched off by configuration (ADR 0001 Q3.4, Q3.5)."""
        errors: list[str] = []
        floor, cap = self.KARNI_MAX_PAGE_SIZE_FLOOR, self.KARNI_MAX_PAGE_SIZE
        if not _positive_int(floor):
            errors.append(
                f"KARNI_MAX_PAGE_SIZE_FLOOR = {floor!r} must be a positive integer (it is the "
                "lowest KARNI_MAX_PAGE_SIZE allowed)"
            )
            floor = 1
        if not _positive_int(cap) or cap < floor:
            errors.append(
                f"KARNI_MAX_PAGE_SIZE = {cap!r} must be an integer >= KARNI_MAX_PAGE_SIZE_FLOOR "
                f"({floor}): a cap of 0/None switches DRF's page-size cap off, and one below "
                "@karni/ui's ResourceTable page size hides rows. Lower "
                "KARNI_MAX_PAGE_SIZE_FLOOR explicitly if this project needs a smaller cap"
            )
            cap = None
        if not self.REST_FRAMEWORK:
            return errors  # DRF not configured here (plain mapping under test)
        page_size = self.REST_FRAMEWORK.get("PAGE_SIZE")
        if page_size is None:
            errors.append(
                "REST_FRAMEWORK['PAGE_SIZE'] is None (or missing), which switches pagination "
                "off for every list. Set a positive integer (KARNI_PAGE_SIZE, default 50). A "
                "viewset that must return plain lists declares pagination = "
                "Unpaginated(max_rows=N, reason='...')"
            )
        elif not _positive_int(page_size):
            errors.append(
                f"REST_FRAMEWORK['PAGE_SIZE'] = {page_size!r} must be a positive "
                "integer. Check KARNI_PAGE_SIZE"
            )
        elif cap is not None and page_size > cap:
            errors.append(
                f"REST_FRAMEWORK['PAGE_SIZE'] = {page_size} exceeds KARNI_MAX_PAGE_SIZE "
                f"({cap}). Lower KARNI_PAGE_SIZE or raise KARNI_MAX_PAGE_SIZE"
            )
        errors.extend(self._check_pagination_class())
        return errors

    def _check_pagination_class(self) -> list[str]:
        dotted = self.REST_FRAMEWORK.get("DEFAULT_PAGINATION_CLASS")
        fix = "Use 'karni.pagination.KarniPageNumberPagination' (or a subclass)"
        if dotted is None:
            return [
                "REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS'] is None (or missing), which "
                f"switches pagination off for every list. {fix}"
            ]
        from django.utils.module_loading import import_string

        from karni.pagination import KarniPagination

        try:
            klass = import_string(dotted) if isinstance(dotted, str) else dotted
        except ImportError as exc:
            return [
                f"REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS'] {dotted!r} cannot be imported: {exc}"
            ]
        if not (isinstance(klass, type) and issubclass(klass, KarniPagination)):
            return [
                f"REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS'] = {dotted!r} is not a "
                f"karni.pagination.KarniPagination subclass (it would skip KARNI_MAX_PAGE_SIZE). "
                f"{fix}"
            ]
        return []

    def _check_performance(self) -> list[str]:
        """Query budgets and API response caching."""
        errors: list[str] = []
        if self.KARNI_QUERY_BUDGET_MODE not in _BUDGET_MODES:
            errors.append(
                f"KARNI_QUERY_BUDGET_MODE {self.KARNI_QUERY_BUDGET_MODE!r} is invalid (expected "
                "'raise', 'warn' or 'off')"
            )
        budget = self.KARNI_QUERY_BUDGET
        if not isinstance(budget, Mapping):
            errors.append(
                f"KARNI_QUERY_BUDGET = {budget!r} must be a dict of action name -> query "
                "count (e.g. {'list': 10})"
            )
        else:
            for action, limit in budget.items():
                if not isinstance(action, str) or not _positive_int(limit):
                    errors.append(
                        f"KARNI_QUERY_BUDGET[{action!r}] = {limit!r} must be a positive "
                        "integer keyed by an action name"
                    )
        if not _positive_int(self.KARNI_API_CACHE_TTL):
            errors.append(
                f"KARNI_API_CACHE_TTL = {self.KARNI_API_CACHE_TTL!r} must be a positive integer "
                "(seconds)"
            )
        if self.KARNI_API_CACHE and self.CACHES and self.KARNI_API_CACHE_ALIAS not in self.CACHES:
            errors.append(
                f"KARNI_API_CACHE_ALIAS {self.KARNI_API_CACHE_ALIAS!r} is not a CACHES alias "
                f"(known: {', '.join(sorted(self.CACHES))})"
            )
        return errors

    def _check_accounts(self) -> list[str]:
        errors: list[str] = []
        if self.KARNI_AUTH_MODE not in _VALID_AUTH_MODES:
            errors.append(
                f"KARNI_AUTH_MODE {self.KARNI_AUTH_MODE!r} is invalid (expected 'jwt' or 'session')"
            )
        if self.KARNI_SOCIAL_AUTH:
            if self.KARNI_AUTH_MODE == "jwt":
                errors.append(
                    "KARNI_SOCIAL_AUTH is not supported with KARNI_AUTH_MODE='jwt' "
                    "(django-allauth's redirect flow is session-mode only). Set "
                    "KARNI_AUTH_MODE='session' or disable KARNI_SOCIAL_AUTH. For JWT mode, "
                    "sign in with an ID token instead: KARNI_SOCIAL_TOKEN_PROVIDERS works in "
                    "both modes and does not need KARNI_SOCIAL_AUTH"
                )
            if not _importable("allauth"):
                errors.append(
                    "KARNI_SOCIAL_AUTH requires django-allauth. Run: pip install 'karni[social]'"
                )
        if self.KARNI_2FA and not _importable("django_otp"):
            errors.append("KARNI_2FA requires django-otp. Run: pip install 'karni[2fa]'")
        for purpose, ttl in self.KARNI_ACCOUNTS_TOKEN_TTL.items():
            if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
                errors.append(
                    f"KARNI_ACCOUNTS_TOKEN_TTL[{purpose!r}] = {ttl!r} must be a "
                    "positive integer (seconds)"
                )
        scheme = urlsplit(self.KARNI_FRONTEND_URL).scheme
        if scheme not in _FRONTEND_SCHEMES:
            errors.append(
                f"KARNI_FRONTEND_URL {self.KARNI_FRONTEND_URL!r} must be an http:// or https:// URL"
            )
        for scope, rate in self.KARNI_AUTH_THROTTLE_RATES.items():
            if rate is None:  # DRF: None disables throttling for the scope
                continue
            if not isinstance(rate, str) or not THROTTLE_RATE_RE.match(rate):
                errors.append(
                    f"KARNI_AUTH_THROTTLE_RATES[{scope!r}] = {rate!r} is not a "
                    "valid throttle rate (expected '<number>/<period>', e.g. "
                    "'10/min', or None to disable)"
                )
        return errors

    def _check_social_token(self) -> list[str]:
        """Sign-in with an ID token (experimental): the providers and their knobs."""
        errors: list[str] = []
        signup = self.KARNI_SOCIAL_TOKEN_SIGNUP
        if signup is not None and signup not in ("open", "approval", "existing"):
            errors.append(
                f"KARNI_SOCIAL_TOKEN_SIGNUP = {signup!r} must be 'open', 'approval', 'existing' "
                "or None (None follows KARNI_ACCOUNTS_REGISTRATION)"
            )
        if not isinstance(self.KARNI_SOCIAL_TOKEN_LINK_VERIFIED, bool):
            errors.append(
                f"KARNI_SOCIAL_TOKEN_LINK_VERIFIED = {self.KARNI_SOCIAL_TOKEN_LINK_VERIFIED!r} "
                "must be True or False"
            )
        leeway = self.KARNI_SOCIAL_TOKEN_LEEWAY
        if not (isinstance(leeway, int) and not isinstance(leeway, bool) and 0 <= leeway <= 300):
            errors.append(
                f"KARNI_SOCIAL_TOKEN_LEEWAY = {leeway!r} must be an integer from 0 to 300 "
                "(seconds of clock skew allowed on exp, iat and nbf)"
            )
        if not _positive_int(self.KARNI_SOCIAL_TOKEN_JWKS_TTL):
            errors.append(
                f"KARNI_SOCIAL_TOKEN_JWKS_TTL = {self.KARNI_SOCIAL_TOKEN_JWKS_TTL!r} must be a "
                "positive integer (seconds a key set stays cached)"
            )
        fetcher = self.KARNI_SOCIAL_TOKEN_JWKS_FETCHER
        if isinstance(fetcher, str) and "." not in fetcher:
            errors.append(
                f"KARNI_SOCIAL_TOKEN_JWKS_FETCHER {fetcher!r} is not a dotted import path"
            )
        providers = self.KARNI_SOCIAL_TOKEN_PROVIDERS
        if providers is None or providers == {}:
            return errors
        if not isinstance(providers, Mapping):
            errors.append(
                f"KARNI_SOCIAL_TOKEN_PROVIDERS = {providers!r} must be a dict of provider name "
                "-> {'client_ids': [...]}, e.g. {'google': {'client_ids': ['<web client id>']}}"
            )
            return errors
        from karni.accounts.social_token import (
            BUILTIN_PROVIDERS,
            PROVIDER_NAME_RE,
            RESERVED_NAMES,
            IdTokenProvider,
            provider_class,
        )

        for name, config in providers.items():
            setting = f"KARNI_SOCIAL_TOKEN_PROVIDERS[{name!r}]"
            if not isinstance(name, str) or not PROVIDER_NAME_RE.match(name):
                errors.append(
                    f"{setting}: a provider name is its URL segment, lowercase letters, digits, "
                    "'-' or '_' (at most 32), starting with a letter"
                )
                continue
            if name in RESERVED_NAMES:
                errors.append(
                    f"{setting}: {name!r} is taken by django-allauth's pages under social/ "
                    f"({', '.join(sorted(RESERVED_NAMES))}). Choose another name"
                )
                continue
            if not isinstance(config, Mapping):
                errors.append(f"{setting} = {config!r} must be a dict with 'client_ids'")
                continue
            path = config.get("class")
            if path is None and name not in BUILTIN_PROVIDERS:
                errors.append(
                    f"{setting}: {name!r} is not a built-in provider "
                    f"({', '.join(BUILTIN_PROVIDERS)}). Add 'class': '<dotted path of an "
                    "IdTokenProvider subclass>'"
                )
                continue
            if path is not None and not (isinstance(path, str) and "." in path):
                errors.append(f"{setting}['class'] {path!r} is not a dotted import path")
                continue
            # A built-in is checked by its own class. A project's class is imported at first
            # use (like every dotted path here), so only the shared keys are checked now.
            checker = provider_class(name, config) if path is None else IdTokenProvider
            found = checker.config_errors(name, config)
            if path is not None:
                found = [line for line in found if "unknown keys" not in line]
            errors.extend(found)
        if not _importable("cryptography"):
            errors.append(
                "KARNI_SOCIAL_TOKEN_PROVIDERS needs the cryptography package to verify RS256 and "
                "ES256 signatures. Run: pip install 'karni[social-token]' (E509)"
            )
        return errors

    def _check_user_grants(self) -> list[str]:
        """Per-user grants (experimental): the switch is a boolean."""
        if not isinstance(self.KARNI_USER_GRANTS, bool):
            return [f"KARNI_USER_GRANTS = {self.KARNI_USER_GRANTS!r} must be True or False"]
        return []

    def _check_navigation(self) -> list[str]:
        """Navigation from data (experimental): the menu's items, and the app for ``"db"``."""
        from karni.navigation import settings_problems

        errors = settings_problems(self.KARNI_NAVIGATION, self.INSTALLED_APPS)
        pages = self.KARNI_NAVIGATION_PAGES
        if not isinstance(pages, list | tuple) or not all(isinstance(p, str) for p in pages):
            errors.append(
                f"KARNI_NAVIGATION_PAGES = {pages!r} must be a list of file paths, e.g. "
                "['frontend/src/routes.tsx'], or [] (E530)"
            )
        return errors

    def _check_email_otp(self) -> list[str]:
        """Sign-in with a code sent by email (experimental): the switch, the code and the policy."""
        from karni.accounts.otp import LENGTH_RANGE, MAX_ATTEMPTS_RANGE, TTL_RANGE
        from karni.accounts.social_token import SIGNUP_POLICIES

        errors: list[str] = []
        if not isinstance(self.KARNI_EMAIL_OTP, bool):
            errors.append(f"KARNI_EMAIL_OTP = {self.KARNI_EMAIL_OTP!r} must be True or False")
        for name, (low, high), what in (
            ("KARNI_EMAIL_OTP_TTL", TTL_RANGE, "seconds a code lives"),
            ("KARNI_EMAIL_OTP_LENGTH", LENGTH_RANGE, "digits in a code"),
            ("KARNI_EMAIL_OTP_MAX_ATTEMPTS", MAX_ATTEMPTS_RANGE, "guesses a code takes"),
        ):
            value = getattr(self, name)
            if not (
                isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
            ):
                errors.append(
                    f"{name} = {value!r} must be an integer from {low} to {high} ({what})"
                )
        signup = self.KARNI_EMAIL_OTP_SIGNUP
        if signup is not None and signup not in SIGNUP_POLICIES:
            errors.append(
                f"KARNI_EMAIL_OTP_SIGNUP = {signup!r} must be 'open', 'approval', 'existing' or "
                "None (None follows KARNI_ACCOUNTS_REGISTRATION)"
            )
        return errors

    def _check_pk(self) -> list[str]:
        """The key type ``karni make model`` writes (experimental): ``uuid`` or ``bigint``."""
        if self.KARNI_PK in ("uuid", "bigint"):
            return []
        return [
            f"KARNI_PK = {self.KARNI_PK!r} must be 'uuid' (BaseModel) or 'bigint' "
            "(BigIntBaseModel): the key type karni make model writes"
        ]

    def _check_terms(self) -> list[str]:
        """Terms acceptance (experimental): ``KARNI_TERMS`` is None or a dict of known keys."""
        from karni.accounts.terms import KNOWN_KEYS, VERSION_MAX_LENGTH

        value = self.KARNI_TERMS
        if value is None:
            return []
        example = '{"version": "2026-11", "url": "/terms/"}'
        if not isinstance(value, Mapping) or not value:
            return [
                f"KARNI_TERMS = {value!r} must be a dict like {example}, or None to ask for no "
                "terms"
            ]
        errors: list[str] = []
        unknown = sorted(str(key) for key in value if key not in KNOWN_KEYS)
        if unknown:
            errors.append(
                f"KARNI_TERMS has unknown keys {unknown} (known: {', '.join(sorted(KNOWN_KEYS))})"
            )
        version = value.get("version")
        if not isinstance(version, str) or not version.strip():
            errors.append(
                f"KARNI_TERMS['version'] = {version!r} must be a non-empty string, e.g. '2026-11'"
            )
        elif len(version) > VERSION_MAX_LENGTH:
            errors.append(
                f"KARNI_TERMS['version'] is {len(version)} characters long: at most "
                f"{VERSION_MAX_LENGTH} are stored"
            )
        url = value.get("url")
        if not isinstance(url, str):
            errors.append(
                f"KARNI_TERMS['url'] = {url!r} must be a string: where the terms are, e.g. "
                "'/terms/' or 'https://example.com/terms/'"
            )
        required = value.get("required", True)
        if not isinstance(required, bool):
            errors.append(f"KARNI_TERMS['required'] = {required!r} must be True or False")
        for key, sample in (("paths", "['/api/']"), ("exempt", "['/api/public/']")):
            if key not in value:
                continue
            entries = value[key]
            if not isinstance(entries, list | tuple) or not all(
                isinstance(entry, str) and entry.startswith("/") for entry in entries
            ):
                errors.append(
                    f"KARNI_TERMS[{key!r}] = {entries!r} must be a list of URL path prefixes "
                    f"that start with '/', e.g. {sample}"
                )
        return errors

    def _check_api(self) -> list[str]:
        errors: list[str] = []
        if self.KARNI_API_MAX_EXPAND_DEPTH < 0:
            errors.append(
                f"KARNI_API_MAX_EXPAND_DEPTH = {self.KARNI_API_MAX_EXPAND_DEPTH!r} must be >= 0"
            )
        # Importability of these dotted paths is deliberately checked at
        # first use, not at startup; only the shape is validated here.
        if "." not in self.KARNI_SEARCH_PROVIDER:
            errors.append(
                f"KARNI_SEARCH_PROVIDER {self.KARNI_SEARCH_PROVIDER!r} is not a dotted import path"
            )
        if "." not in self.KARNI_API_ROUTER:
            errors.append(f"KARNI_API_ROUTER {self.KARNI_API_ROUTER!r} is not a dotted import path")
        rate = self.KARNI_PUBLIC_CREATE_RATE
        if rate and not THROTTLE_RATE_RE.match(rate):
            errors.append(
                f"KARNI_PUBLIC_CREATE_RATE = {rate!r} is not a valid throttle rate (expected "
                "'<number>/<period>', e.g. '10/hour', or None to turn the default limit off)"
            )
        return errors

    def _check_security_headers(self) -> list[str]:
        """``KARNI_CSP`` and ``KARNI_PERMISSIONS_POLICY``: a dict of name -> sources, or None."""
        errors: list[str] = []
        for setting, example in (
            ("KARNI_CSP", '{"font-src": ["https://fonts.gstatic.com"]}'),
            ("KARNI_PERMISSIONS_POLICY", '{"geolocation": ["self"]}'),
        ):
            value = getattr(self, setting)
            if value is None:
                continue
            if not isinstance(value, Mapping):
                errors.append(
                    f"{setting} = {value!r} must be a dict of name -> list of sources, e.g. "
                    f"{example}, or None to send no header"
                )
                continue
            for name, sources in value.items():
                if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z-]*", name):
                    errors.append(f"{setting} key {name!r} is not a directive name, e.g. {example}")
                elif sources is not None and not (
                    isinstance(sources, str)
                    or (
                        isinstance(sources, list | tuple)
                        and all(isinstance(item, str) for item in sources)
                    )
                ):
                    errors.append(
                        f"{setting}[{name!r}] = {sources!r} must be a list of strings, or None "
                        "to remove the entry"
                    )
        return errors

    def _check_admin(self) -> list[str]:
        errors: list[str] = []
        apps = [app for app in self.INSTALLED_APPS if isinstance(app, str)]
        if "unfold" in apps and "django.contrib.admin" in apps:
            if apps.index("unfold") > apps.index("django.contrib.admin"):
                errors.append(
                    "INSTALLED_APPS must list 'unfold' before "
                    "'django.contrib.admin' (unfold's templates override the "
                    "admin's). Move 'unfold' up or let karni_settings() manage "
                    "INSTALLED_APPS"
                )
        for entry in self.KARNI_ADMIN_EXCLUDE:
            if not isinstance(entry, str):
                errors.append(
                    f"KARNI_ADMIN_EXCLUDE entry {entry!r} must be a string "
                    "(an app_label or 'app_label.ModelName')"
                )
        for entry in self.KARNI_MATRIX_EXCLUDE:
            if not isinstance(entry, str):
                errors.append(
                    f"KARNI_MATRIX_EXCLUDE entry {entry!r} must be a string "
                    "(an app_label or 'app_label.ModelName')"
                )
        # Read per request by the admin, so a bad value set after the call is caught here.
        from karni.conf.admin_logo import logo_paths

        try:
            logo_paths(self.KARNI_ADMIN_LOGO)
        except KarniImproperlyConfigured as exc:
            errors.append(f"{exc.message.rstrip('.')} (E303)")
        for name in (
            "KARNI_ADMIN_LIST_DISPLAY_MAX",
            "KARNI_ADMIN_LIST_FILTER_MAX",
            "KARNI_ADMIN_SEARCH_MAX",
        ):
            value = getattr(self, name)
            if value <= 0:
                errors.append(f"{name} = {value!r} must be a positive integer")
        return errors

    def _check_karni_knobs(self) -> list[str]:
        errors: list[str] = []
        for path in self.KARNI_HEALTH_CHECKS:
            if "." not in path:
                errors.append(f"KARNI_HEALTH_CHECKS entry {path!r} is not a dotted import path")
        if self.KARNI_HEALTH_CELERY_TIMEOUT <= 0:
            errors.append(
                f"KARNI_HEALTH_CELERY_TIMEOUT = {self.KARNI_HEALTH_CELERY_TIMEOUT!r} "
                "must be greater than 0"
            )
        if "." not in self.KARNI_THUMBNAILER:
            errors.append(
                f"KARNI_THUMBNAILER {self.KARNI_THUMBNAILER!r} is not a dotted import path"
            )
        return errors


def validate_settings(settings: Any) -> None:
    """Validate a settings container, raising ``ImproperlyConfigured`` on failure.

    Accepts anything settings-shaped: Django's ``LazySettings``, a plain
    module, a namespace produced by ``karni_settings(globals())``, or any
    mapping. Every failure is collected and reported in one error message so
    a misconfigured deployment surfaces all its problems at once.

    Called automatically from ``KarniAppConfig.ready()`` at startup.

    Override / escape hatch: set ``KARNI_VALIDATE = False`` in your settings
    to skip the startup call, or call this function (or your own
    ``KarniSettingsModel`` subclass) manually wherever you prefer.

    :param settings: the settings object or mapping to validate.
    :raises ImproperlyConfigured: listing every invalid value found.
    """
    data: dict[str, Any] = {}
    for name in KarniSettingsModel.model_fields:
        if isinstance(settings, Mapping):
            if name in settings:
                data[name] = settings[name]
        elif hasattr(settings, name):
            data[name] = getattr(settings, name)

    try:
        KarniSettingsModel.model_validate(data)
    except ValidationError as exc:
        lines: list[str] = []
        for error in exc.errors():
            loc = ".".join(str(part) for part in error["loc"])
            message = error["msg"].removeprefix("Value error, ")
            for part in message.splitlines():
                lines.append(f"  - {loc + ': ' if loc else ''}{part}")
        raise KarniImproperlyConfigured(
            "Karni settings validation failed:\n"
            + "\n".join(lines)
            + "\n(set KARNI_VALIDATE = False in settings.py to skip startup validation)",
            code="E504",
        ) from exc
