"""Startup validation of the merged Karni settings.

A Pydantic v2 model checks the values that most often break deployments
(secret key, hosts, database, Redis URLs, storage selection, throttle rates,
pagination that cannot be switched off, query budgets and API caching, auth
mode and social/2FA extras, API knobs, admin app ordering, health-check
configuration) and :func:`validate_settings` turns any problem
into a single ``ImproperlyConfigured`` error listing *every* failure, so a
bad container config dies loudly at startup instead of at 3 a.m.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Mapping
from typing import Any
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
    AWS_STORAGE_BUCKET_NAME: str = ""
    KARNI_AUTH_MODE: str = "jwt"
    KARNI_SOCIAL_AUTH: bool = False
    KARNI_2FA: bool = False
    KARNI_FRONTEND_URL: str = "http://localhost:5173"
    KARNI_ACCOUNTS_TOKEN_TTL: dict[str, Any] = Field(default_factory=dict)
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
    KARNI_ADMIN_PATH: str = "admin/"
    KARNI_ACCOUNTS_HONEYPOT_FIELD: str = "website"
    KARNI_ADMIN_LIST_DISPLAY_MAX: int = 6
    KARNI_ADMIN_LIST_FILTER_MAX: int = 6
    KARNI_ADMIN_SEARCH_MAX: int = 5
    KARNI_HEALTH_CHECKS: list[str] = Field(default_factory=list)
    KARNI_HEALTH_CELERY_TIMEOUT: float = 1.0
    KARNI_THUMBNAILER: str = "karni.storage.thumbnails.make_thumbnail"
    KARNI_AUDIT_ASYNC: bool = False
    KARNI_AUDIT_RETENTION_DAYS: int | None = None
    KARNI_AUDIT_REDACT: list[str] = Field(default_factory=list)

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
        errors.extend(self._check_api())
        errors.extend(self._check_admin())
        errors.extend(self._check_karni_knobs())
        return errors

    def _check_secret_key(self) -> list[str]:
        if not self.SECRET_KEY.strip():
            return ["SECRET_KEY must not be empty"]
        if not self.DEBUG and self.SECRET_KEY == INSECURE_SECRET_KEY:
            return [
                "SECRET_KEY is the insecure Karni dev default; set a real "
                "SECRET_KEY environment variable when DEBUG is False"
            ]
        return []

    def _check_allowed_hosts(self) -> list[str]:
        if not self.DEBUG and not self.ALLOWED_HOSTS:
            return [
                "ALLOWED_HOSTS must not be empty when DEBUG is False; set the "
                "ALLOWED_HOSTS environment variable (comma-separated)"
            ]
        return []

    def _check_databases(self) -> list[str]:
        default = self.DATABASES.get("default")
        if not isinstance(default, Mapping) or not default.get("ENGINE"):
            return [
                "DATABASES must define a 'default' connection with an ENGINE; "
                "set DATABASE_URL or override DATABASES in settings.py"
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
                        "(expected scheme redis://, rediss:// or unix://); check REDIS_URL"
                    )
        return errors

    def _check_celery_broker(self) -> list[str]:
        if not self.CELERY_BROKER_URL:
            return []
        scheme = urlsplit(self.CELERY_BROKER_URL).scheme
        if not scheme:
            return [
                f"CELERY_BROKER_URL {self.CELERY_BROKER_URL!r} is not a URL "
                "(expected e.g. redis://redis:6379/0); check REDIS_URL"
            ]
        return []

    def _check_storage(self) -> list[str]:
        errors: list[str] = []
        if self.KARNI_STORAGE not in _VALID_STORAGES:
            errors.append(
                f"KARNI_STORAGE {self.KARNI_STORAGE!r} is invalid; expected 'local' or 's3'"
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
                        "e.g. '100/min'); check THROTTLE_ANON / THROTTLE_USER"
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
                "off for every list; set a positive integer (KARNI_PAGE_SIZE, default 50). A "
                "viewset that must return plain lists declares pagination = "
                "Unpaginated(max_rows=N, reason='...')"
            )
        elif not _positive_int(page_size):
            errors.append(
                f"REST_FRAMEWORK['PAGE_SIZE'] = {page_size!r} must be a positive "
                "integer; check KARNI_PAGE_SIZE"
            )
        elif cap is not None and page_size > cap:
            errors.append(
                f"REST_FRAMEWORK['PAGE_SIZE'] = {page_size} exceeds KARNI_MAX_PAGE_SIZE "
                f"({cap}); lower KARNI_PAGE_SIZE or raise KARNI_MAX_PAGE_SIZE"
            )
        errors.extend(self._check_pagination_class())
        return errors

    def _check_pagination_class(self) -> list[str]:
        dotted = self.REST_FRAMEWORK.get("DEFAULT_PAGINATION_CLASS")
        fix = "use 'karni.pagination.KarniPageNumberPagination' (or a subclass)"
        if dotted is None:
            return [
                "REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS'] is None (or missing), which "
                f"switches pagination off for every list; {fix}"
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
                f"karni.pagination.KarniPagination subclass (it would skip KARNI_MAX_PAGE_SIZE); "
                f"{fix}"
            ]
        return []

    def _check_performance(self) -> list[str]:
        """Query budgets and API response caching."""
        errors: list[str] = []
        if self.KARNI_QUERY_BUDGET_MODE not in _BUDGET_MODES:
            errors.append(
                f"KARNI_QUERY_BUDGET_MODE {self.KARNI_QUERY_BUDGET_MODE!r} is invalid; expected "
                "'raise', 'warn' or 'off'"
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
                f"KARNI_AUTH_MODE {self.KARNI_AUTH_MODE!r} is invalid; expected 'jwt' or 'session'"
            )
        if self.KARNI_SOCIAL_AUTH:
            if self.KARNI_AUTH_MODE == "jwt":
                errors.append(
                    "KARNI_SOCIAL_AUTH is not supported with KARNI_AUTH_MODE='jwt' "
                    "in karni 0.1 (social auth is session-mode only; an "
                    "allauth-headless JWT strategy is future work). Set "
                    "KARNI_AUTH_MODE='session' or disable KARNI_SOCIAL_AUTH"
                )
            if not _importable("allauth"):
                errors.append(
                    "KARNI_SOCIAL_AUTH requires django-allauth; run: pip install 'karni[social]'"
                )
        if self.KARNI_2FA and not _importable("django_otp"):
            errors.append("KARNI_2FA requires django-otp; run: pip install 'karni[2fa]'")
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
        return errors

    def _check_admin(self) -> list[str]:
        errors: list[str] = []
        apps = [app for app in self.INSTALLED_APPS if isinstance(app, str)]
        if "unfold" in apps and "django.contrib.admin" in apps:
            if apps.index("unfold") > apps.index("django.contrib.admin"):
                errors.append(
                    "INSTALLED_APPS must list 'unfold' before "
                    "'django.contrib.admin' (unfold's templates override the "
                    "admin's); move 'unfold' up or let karni_settings() manage "
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
