"""Tests for karni.conf: merge semantics, profiles, logging and validation."""

from __future__ import annotations

from typing import Any

import pytest
import structlog
from django.core.exceptions import ImproperlyConfigured

from karni.conf import karni_settings
from karni.conf.base import BASE, INSECURE_SECRET_KEY
from karni.conf.dev import DEV
from karni.conf.prod import PROD
from karni.conf.validation import validate_settings
from karni.pagination import KarniPageNumberPagination

# Deterministic prod overrides: independent of ambient env vars read at import.
PROD_OK: dict[str, Any] = {
    "DEBUG": False,
    "SECRET_KEY": "a-real-production-secret-key-of-decent-length",
    "ALLOWED_HOSTS": ["example.com"],
}


# ---------------------------------------------------------------------------
# Merge / setdefault semantics
# ---------------------------------------------------------------------------


def test_setdefault_never_overwrites_existing_names(make_settings) -> None:
    ns = make_settings(
        "dev",
        preset={"TIME_ZONE": "Asia/Kolkata", "REST_FRAMEWORK": {"PAGE_SIZE": 5}},
    )
    assert ns["TIME_ZONE"] == "Asia/Kolkata"
    assert ns["REST_FRAMEWORK"] == {"PAGE_SIZE": 5}
    # Everything not predefined still arrives.
    assert ns["SPECTACULAR_SETTINGS"]["VERSION"] == "0.1.0"
    assert ns["CELERY_RESULT_BACKEND"] == "django-db"


def test_overrides_clobber_defaults_but_not_namespace(make_settings) -> None:
    ns = make_settings(
        "dev",
        preset={"TIME_ZONE": "UTC"},
        TIME_ZONE="Europe/Paris",
        CELERY_TASK_TIME_LIMIT=10,
    )
    # Pre-existing namespace name beats the keyword override...
    assert ns["TIME_ZONE"] == "UTC"
    # ...but the override beats BASE.
    assert ns["CELERY_TASK_TIME_LIMIT"] == 10
    assert BASE["CELERY_TASK_TIME_LIMIT"] == 300


def test_assignment_after_call_wins() -> None:
    ns: dict[str, Any] = {}
    karni_settings(ns, env_name="dev")
    ns["REST_FRAMEWORK"] = {"PAGE_SIZE": 7}  # a settings.py line below the call
    assert ns["REST_FRAMEWORK"] == {"PAGE_SIZE": 7}


def test_installed_apps_merge_preserves_user_order(make_settings) -> None:
    ns = make_settings("dev", preset={"INSTALLED_APPS": ["myapp", "django.contrib.admin"]})
    apps = ns["INSTALLED_APPS"]
    assert apps[0] == "myapp"
    # The one merge exception: Karni's appended "unfold" entry is inserted
    # immediately before django.contrib.admin (its templates must override
    # the admin's) instead of after the user's entries.
    admin_index = apps.index("django.contrib.admin")
    assert apps[admin_index - 1] == "unfold"
    assert apps.count("django.contrib.admin") == 1
    for karni_app in ("rest_framework", "django_celery_beat", "karni"):
        assert karni_app in apps
    assert len(apps) == len(set(apps))


def test_middleware_merge_dedupes(make_settings) -> None:
    ns = make_settings(
        "dev",
        preset={
            "MIDDLEWARE": [
                "myapp.middleware.TenantMiddleware",
                "django.middleware.security.SecurityMiddleware",
            ]
        },
    )
    middleware = ns["MIDDLEWARE"]
    assert middleware[0] == "myapp.middleware.TenantMiddleware"
    assert middleware.count("django.middleware.security.SecurityMiddleware") == 1
    assert "django_structlog.middlewares.RequestMiddleware" in middleware


def test_fresh_namespace_gets_base_lists(make_settings) -> None:
    ns = make_settings("dev")
    assert ns["INSTALLED_APPS"] == BASE["INSTALLED_APPS"]
    assert ns["MIDDLEWARE"] == BASE["MIDDLEWARE"]
    # Same content, but never the same list object as BASE.
    assert ns["INSTALLED_APPS"] is not BASE["INSTALLED_APPS"]


def test_deep_copy_isolates_calls_and_base(make_settings) -> None:
    ns1 = make_settings("dev")
    ns2 = make_settings("dev")

    ns1["INSTALLED_APPS"].append("mutant")
    ns1["REST_FRAMEWORK"]["PAGE_SIZE"] = 1
    ns1["CACHES"]["default"]["LOCATION"] = "redis://elsewhere:6379/9"
    ns1["KARNI_HEALTH_CHECKS"].clear()

    assert "mutant" not in ns2["INSTALLED_APPS"]
    assert ns2["REST_FRAMEWORK"]["PAGE_SIZE"] == BASE["REST_FRAMEWORK"]["PAGE_SIZE"]
    assert ns2["CACHES"]["default"]["LOCATION"] != "redis://elsewhere:6379/9"
    assert ns2["KARNI_HEALTH_CHECKS"] == BASE["KARNI_HEALTH_CHECKS"]

    assert "mutant" not in BASE["INSTALLED_APPS"]
    assert BASE["REST_FRAMEWORK"]["PAGE_SIZE"] == ns2["REST_FRAMEWORK"]["PAGE_SIZE"]
    assert BASE["KARNI_HEALTH_CHECKS"], "BASE health checks were corrupted"


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def test_dev_profile(make_settings) -> None:
    ns = make_settings("dev")
    assert ns["EMAIL_BACKEND"] == "django.core.mail.backends.console.EmailBackend"
    assert ns["CORS_ALLOW_ALL_ORIGINS"] is True
    assert ns["KARNI_JSON_LOGS"] is False
    assert "SECURE_SSL_REDIRECT" not in ns
    assert "SECURE_HSTS_SECONDS" not in ns


def test_prod_profile_security_headers(make_settings) -> None:
    ns = make_settings("prod", **PROD_OK)
    assert ns["DEBUG"] is False
    assert ns["SECURE_SSL_REDIRECT"] is True
    assert ns["SECURE_HSTS_SECONDS"] == 31536000
    assert ns["SECURE_HSTS_INCLUDE_SUBDOMAINS"] is True
    assert ns["SECURE_HSTS_PRELOAD"] is True
    assert ns["SECURE_CONTENT_TYPE_NOSNIFF"] is True
    assert ns["SECURE_PROXY_SSL_HEADER"] == ("HTTP_X_FORWARDED_PROTO", "https")
    assert ns["SESSION_COOKIE_SECURE"] is True
    assert ns["CSRF_COOKIE_SECURE"] is True
    assert ns["X_FRAME_OPTIONS"] == "DENY"
    assert ns["SECURE_REFERRER_POLICY"] == "same-origin"
    assert ns["KARNI_JSON_LOGS"] is True


def test_unknown_profile_raises() -> None:
    with pytest.raises(ImproperlyConfigured, match="staging"):
        karni_settings({}, env_name="staging")


def test_profile_read_from_django_env(monkeypatch: pytest.MonkeyPatch, make_settings) -> None:
    monkeypatch.setenv("DJANGO_ENV", "prod")
    ns = make_settings(env_name=None, **PROD_OK)
    assert ns["SECURE_SSL_REDIRECT"] is True


def test_profile_dicts_do_not_leak_into_each_other() -> None:
    assert "SECURE_SSL_REDIRECT" not in DEV
    assert "EMAIL_BACKEND" not in PROD


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _final_renderer(ns: dict[str, Any]) -> Any:
    return ns["LOGGING"]["formatters"]["structlog"]["processors"][-1]


def test_dev_logging_uses_console_renderer(make_settings) -> None:
    ns = make_settings("dev")
    assert isinstance(_final_renderer(ns), structlog.dev.ConsoleRenderer)


def test_prod_logging_uses_json_renderer(make_settings) -> None:
    ns = make_settings("prod", **PROD_OK)
    assert isinstance(_final_renderer(ns), structlog.processors.JSONRenderer)


def test_karni_json_logs_override_flips_renderer(make_settings) -> None:
    ns = make_settings("dev", KARNI_JSON_LOGS=True)
    assert isinstance(_final_renderer(ns), structlog.processors.JSONRenderer)


def test_user_logging_left_untouched(make_settings) -> None:
    mine = {"version": 1, "disable_existing_loggers": False}
    ns = make_settings("dev", preset={"LOGGING": mine})
    assert ns["LOGGING"] is mine


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_dev_defaults_pass(make_settings) -> None:
    ns = make_settings("dev", DEBUG=True)
    validate_settings(ns)  # must not raise


def test_validate_prod_with_good_values_passes(make_settings) -> None:
    ns = make_settings("prod", **PROD_OK)
    validate_settings(ns)  # must not raise


def test_validate_prod_rejects_insecure_secret_key(make_settings) -> None:
    ns = make_settings(
        "prod",
        DEBUG=False,
        SECRET_KEY=INSECURE_SECRET_KEY,
        ALLOWED_HOSTS=["example.com"],
    )
    with pytest.raises(ImproperlyConfigured, match="SECRET_KEY"):
        validate_settings(ns)


def test_validate_prod_rejects_empty_allowed_hosts(make_settings) -> None:
    ns = make_settings("prod", **{**PROD_OK, "ALLOWED_HOSTS": []})
    with pytest.raises(ImproperlyConfigured, match="ALLOWED_HOSTS"):
        validate_settings(ns)


def test_validate_rejects_bad_throttle_rate(make_settings) -> None:
    ns = make_settings("dev", DEBUG=True)
    ns["REST_FRAMEWORK"]["DEFAULT_THROTTLE_RATES"]["anon"] = "loads/fortnight"
    with pytest.raises(ImproperlyConfigured, match="DEFAULT_THROTTLE_RATES"):
        validate_settings(ns)


def test_validate_allows_none_throttle_rate(make_settings) -> None:
    ns = make_settings("dev", DEBUG=True)
    ns["REST_FRAMEWORK"]["DEFAULT_THROTTLE_RATES"]["anon"] = None
    validate_settings(ns)  # DRF: None disables the scope


def test_validate_rejects_unknown_storage(make_settings) -> None:
    ns = make_settings("dev", DEBUG=True, KARNI_STORAGE="gcs")
    with pytest.raises(ImproperlyConfigured, match="KARNI_STORAGE"):
        validate_settings(ns)


def test_validate_s3_requires_bucket(make_settings) -> None:
    ns = make_settings("dev", DEBUG=True, KARNI_STORAGE="s3", AWS_STORAGE_BUCKET_NAME="")
    with pytest.raises(ImproperlyConfigured, match="AWS_STORAGE_BUCKET_NAME"):
        validate_settings(ns)

    ns = make_settings("dev", DEBUG=True, KARNI_STORAGE="s3", AWS_STORAGE_BUCKET_NAME="bucket")
    validate_settings(ns)  # must not raise


def test_validate_rejects_non_redis_cache_location(make_settings) -> None:
    ns = make_settings("dev", DEBUG=True)
    ns["CACHES"]["default"]["LOCATION"] = "memcached://example:11211"
    with pytest.raises(ImproperlyConfigured, match="Redis"):
        validate_settings(ns)


def test_validate_allows_non_redis_cache_backend(make_settings) -> None:
    ns = make_settings(
        "dev",
        DEBUG=True,
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        },
    )
    validate_settings(ns)  # scheme check only applies to RedisCache


def test_validate_rejects_bad_health_timeout(make_settings) -> None:
    ns = make_settings("dev", DEBUG=True, KARNI_HEALTH_CELERY_TIMEOUT=0)
    with pytest.raises(ImproperlyConfigured, match="KARNI_HEALTH_CELERY_TIMEOUT"):
        validate_settings(ns)


def test_validation_reports_all_errors_at_once(make_settings) -> None:
    ns = make_settings(
        "prod",
        DEBUG=False,
        SECRET_KEY=INSECURE_SECRET_KEY,
        ALLOWED_HOSTS=[],
        KARNI_STORAGE="gcs",
    )
    with pytest.raises(ImproperlyConfigured) as excinfo:
        validate_settings(ns)
    message = str(excinfo.value)
    assert "SECRET_KEY" in message
    assert "ALLOWED_HOSTS" in message
    assert "KARNI_STORAGE" in message
    assert "KARNI_VALIDATE" in message  # points at the escape hatch


def test_validate_accepts_django_lazy_settings() -> None:
    from django.conf import settings

    validate_settings(settings)  # the live test settings must be valid


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pagination_defaults() -> None:
    assert KarniPageNumberPagination.page_size_query_param == "page_size"
    assert KarniPageNumberPagination().get_max_page_size() == BASE["KARNI_MAX_PAGE_SIZE"] == 100
    assert BASE["KARNI_MAX_PAGE_SIZE_FLOOR"] == 25
    assert (
        BASE["REST_FRAMEWORK"]["DEFAULT_PAGINATION_CLASS"]
        == "karni.pagination.KarniPageNumberPagination"
    )


# ---------------------------------------------------------------------------
# Performance settings (ADR 0001 Decision 3)
# ---------------------------------------------------------------------------


def test_validate_refuses_page_size_none(make_settings) -> None:
    ns = make_settings("dev", DEBUG=True)
    ns["REST_FRAMEWORK"]["PAGE_SIZE"] = None
    with pytest.raises(ImproperlyConfigured, match=r"PAGE_SIZE'\] is None"):
        validate_settings(ns)
    del ns["REST_FRAMEWORK"]["PAGE_SIZE"]
    with pytest.raises(ImproperlyConfigured, match="switches pagination off"):
        validate_settings(ns)


@pytest.mark.parametrize(
    ("dotted", "message"),
    [
        (None, "DEFAULT_PAGINATION_CLASS'] is None"),
        ("rest_framework.pagination.PageNumberPagination", "not a karni.pagination"),
        ("nowhere.Missing", "cannot be imported"),
    ],
)
def test_validate_refuses_non_karni_pagination(make_settings, dotted, message) -> None:
    ns = make_settings("dev", DEBUG=True)
    ns["REST_FRAMEWORK"]["DEFAULT_PAGINATION_CLASS"] = dotted
    with pytest.raises(ImproperlyConfigured, match=message):
        validate_settings(ns)


def test_validate_accepts_any_karni_paginator(make_settings) -> None:
    ns = make_settings("dev", DEBUG=True)
    ns["REST_FRAMEWORK"]["DEFAULT_PAGINATION_CLASS"] = "karni.pagination.KarniCursorPagination"
    validate_settings(ns)  # must not raise


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"KARNI_MAX_PAGE_SIZE": 10}, "KARNI_MAX_PAGE_SIZE = 10 must be an integer >= "),
        ({"KARNI_MAX_PAGE_SIZE": None}, "switches DRF's page-size cap off"),
        ({"KARNI_MAX_PAGE_SIZE": 0}, "KARNI_MAX_PAGE_SIZE = 0"),
        ({"KARNI_MAX_PAGE_SIZE_FLOOR": 0}, "KARNI_MAX_PAGE_SIZE_FLOOR = 0"),
        ({"KARNI_MAX_PAGE_SIZE": 40}, r"PAGE_SIZE'\] = 50 exceeds KARNI_MAX_PAGE_SIZE \(40\)"),
    ],
)
def test_validate_page_size_cap_and_floor(make_settings, overrides, message) -> None:
    ns = make_settings("dev", DEBUG=True, **overrides)
    with pytest.raises(ImproperlyConfigured, match=message):
        validate_settings(ns)


def test_a_lower_floor_is_an_explicit_choice(make_settings) -> None:
    ns = make_settings("dev", DEBUG=True, KARNI_MAX_PAGE_SIZE=10, KARNI_MAX_PAGE_SIZE_FLOOR=5)
    ns["REST_FRAMEWORK"]["PAGE_SIZE"] = 10
    validate_settings(ns)  # must not raise


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"KARNI_QUERY_BUDGET_MODE": "loud"}, "KARNI_QUERY_BUDGET_MODE 'loud' is invalid"),
        ({"KARNI_QUERY_BUDGET": {"list": 0}}, r"KARNI_QUERY_BUDGET\['list'\] = 0"),
        ({"KARNI_QUERY_BUDGET": 8}, "must be a dict"),
        ({"KARNI_API_CACHE_TTL": 0}, "KARNI_API_CACHE_TTL = 0"),
        ({"KARNI_API_CACHE": True, "KARNI_API_CACHE_ALIAS": "nope"}, "is not a CACHES alias"),
    ],
)
def test_validate_budget_and_cache_settings(make_settings, overrides, message) -> None:
    ns = make_settings("dev", DEBUG=True, **overrides)
    with pytest.raises(ImproperlyConfigured, match=message):
        validate_settings(ns)


def test_performance_defaults(make_settings) -> None:
    ns = make_settings("prod", **PROD_OK)
    assert ns["KARNI_MAX_PAGE_SIZE"] == 100 and ns["KARNI_MAX_PAGE_SIZE_FLOOR"] == 25
    assert ns["KARNI_QUERY_BUDGET"] == {
        "list": 8,
        "retrieve": 8,
        "create": 12,
        "update": 12,
        "partial_update": 12,
        "destroy": 10,
        "*": 15,
    }
    assert ns["KARNI_API_CACHE"] is False and ns["KARNI_API_CACHE_TTL"] == 300
    validate_settings(ns)
