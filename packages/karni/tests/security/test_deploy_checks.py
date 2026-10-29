"""Deploy checks karni.W510 to W520: ``manage.py check --deploy`` and ``karni check --deploy``.

Each check is tested both ways: silent with production values, and
reporting its code with the scaffold's development values.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import pytest
from django.core import checks
from django.core.management import call_command
from django.test import override_settings

from karni.exceptions import KarniCommandError
from karni.security import checks as deploy

pytestmark = pytest.mark.django_db

STRONG_KEY = "k8#Qz!v2@Lm9$Rt4^Wx7&Yp1*Bn6(Cs3)Dg5_Fh0+Jk-Ul=Om~Pq"
PRODUCTION: dict[str, Any] = {
    "DEBUG": False,
    "SECRET_KEY": STRONG_KEY,
    "ALLOWED_HOSTS": ["example.com"],
    "CSRF_TRUSTED_ORIGINS": ["https://example.com"],
    "SECURE_HSTS_SECONDS": 31536000,
    "SESSION_COOKIE_SECURE": True,
    "CSRF_COOKIE_SECURE": True,
    "CORS_ALLOW_ALL_ORIGINS": False,
    "CORS_ALLOWED_ORIGINS": ["https://example.com"],
    "KARNI_CSP": {},
    "KARNI_CSP_REPORT_ONLY": None,
    "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "DEFAULT_FROM_EMAIL": "Example Site <noreply@example.com>",
    # The admin at staff-area/ (tests.urls mounts it at admin/).
    "ROOT_URLCONF": "tests.security.urls",
}
#: What the scaffold's .env.example gives a new project.
DEVELOPMENT: dict[str, Any] = {
    "DEBUG": True,
    "SECRET_KEY": "karni-insecure-dev-key",
    "ALLOWED_HOSTS": ["*"],
    "CSRF_TRUSTED_ORIGINS": [],
    "SECURE_HSTS_SECONDS": 0,
    "SESSION_COOKIE_SECURE": False,
    "CSRF_COOKIE_SECURE": False,
    "CORS_ALLOW_ALL_ORIGINS": True,
    "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
    "DEFAULT_FROM_EMAIL": "webmaster@localhost",
    "ROOT_URLCONF": "tests.urls",
}

UNSENT = "django.core.mail.backends."

Check = Callable[..., list[checks.CheckMessage]]
CHECKS: list[Check] = [
    deploy.check_debug,
    deploy.check_secret_key,
    deploy.check_allowed_hosts,
    deploy.check_csrf_trusted_origins,
    deploy.check_hsts,
    deploy.check_secure_cookies,
    deploy.check_admin_path,
    deploy.check_cors,
    deploy.check_csp_present,
    deploy.check_csp_scripts,
    deploy.check_email,
]


def _ids(messages: list[checks.CheckMessage]) -> list[str]:
    return [str(message.id) for message in messages]


@override_settings(**PRODUCTION)
@pytest.mark.parametrize("check", CHECKS, ids=lambda check: check.__name__)
def test_production_values_pass(check: Check) -> None:
    assert check() == []


@pytest.mark.parametrize(
    ("check", "values", "code"),
    [
        (deploy.check_debug, {"DEBUG": True}, "karni.W510"),
        (deploy.check_secret_key, {"SECRET_KEY": "karni-insecure-dev-key"}, "karni.W511"),
        (deploy.check_secret_key, {"SECRET_KEY": "django-insecure-" + "x1y2z3" * 10}, "karni.W511"),
        (deploy.check_secret_key, {"SECRET_KEY": "short-but-random-Q8!"}, "karni.W511"),
        (deploy.check_secret_key, {"SECRET_KEY": "abab" * 20}, "karni.W511"),
        (deploy.check_allowed_hosts, {"ALLOWED_HOSTS": ["*"]}, "karni.W512"),
        (deploy.check_allowed_hosts, {"ALLOWED_HOSTS": []}, "karni.W512"),
        (deploy.check_csrf_trusted_origins, {"CSRF_TRUSTED_ORIGINS": []}, "karni.W513"),
        (deploy.check_csrf_trusted_origins, {"CSRF_TRUSTED_ORIGINS": ["https://*"]}, "karni.W513"),
        (
            deploy.check_csrf_trusted_origins,
            {"CSRF_TRUSTED_ORIGINS": ["https://example.com", "http://localhost:5173"]},
            "karni.W513",
        ),
        (deploy.check_hsts, {"SECURE_HSTS_SECONDS": 0}, "karni.W514"),
        (deploy.check_secure_cookies, {"SESSION_COOKIE_SECURE": False}, "karni.W515"),
        (deploy.check_secure_cookies, {"CSRF_COOKIE_SECURE": False}, "karni.W515"),
        (deploy.check_admin_path, {"ROOT_URLCONF": "tests.urls"}, "karni.W516"),
        (deploy.check_cors, {"CORS_ALLOW_ALL_ORIGINS": True}, "karni.W517"),
        (deploy.check_cors, {"CORS_ALLOWED_ORIGINS": ["*"]}, "karni.W517"),
        (deploy.check_cors, {"CORS_ALLOWED_ORIGIN_REGEXES": [r"^https://.*$"]}, "karni.W517"),
        (deploy.check_csp_present, {"KARNI_CSP": None}, "karni.W518"),
        (deploy.check_csp_present, {"KARNI_CSP_REPORT_ONLY": True}, "karni.W518"),
        (deploy.check_csp_present, {"DEBUG": True}, "karni.W518"),
        (deploy.check_csp_scripts, {"KARNI_CSP": {"script-src": ["'unsafe-eval'"]}}, "karni.W519"),
        (deploy.check_csp_scripts, {"KARNI_CSP": {"script-src": ["https:"]}}, "karni.W519"),
        (
            deploy.check_csp_scripts,
            {"KARNI_CSP": {"script-src": None, "default-src": ["'unsafe-inline'"]}},
            "karni.W519",
        ),
        (
            deploy.check_csp_scripts,
            {"KARNI_CSP": {"script-src": None, "default-src": None}},
            "karni.W519",
        ),
        (deploy.check_email, {"EMAIL_BACKEND": UNSENT + "console.EmailBackend"}, "karni.W520"),
        (deploy.check_email, {"EMAIL_BACKEND": UNSENT + "locmem.EmailBackend"}, "karni.W520"),
        (deploy.check_email, {"EMAIL_BACKEND": UNSENT + "dummy.EmailBackend"}, "karni.W520"),
        (deploy.check_email, {"DEFAULT_FROM_EMAIL": "webmaster@localhost"}, "karni.W520"),
        (deploy.check_email, {"DEFAULT_FROM_EMAIL": "Site <site@app.localhost>"}, "karni.W520"),
        (deploy.check_email, {"DEFAULT_FROM_EMAIL": ""}, "karni.W520"),
    ],
)
def test_each_finding_reports_its_code(check: Check, values: dict[str, Any], code: str) -> None:
    with override_settings(**{**PRODUCTION, **values}):
        messages = check()
    assert _ids(messages) == [code]
    assert messages[0].level == checks.WARNING
    assert messages[0].hint  # the fix, from the error code registry


@override_settings(**PRODUCTION)
def test_a_narrow_cors_regex_and_a_script_host_pass() -> None:
    with override_settings(CORS_ALLOWED_ORIGIN_REGEXES=[r"^https://\w+\.example\.com$"]):
        assert deploy.check_cors() == []
    with override_settings(KARNI_CSP={"script-src": ["https://plausible.io"]}):
        assert deploy.check_csp_scripts() == []


@override_settings(**{**PRODUCTION, "KARNI_CSP": {"script-src": ["'unsafe-inline'"]}})
def test_unsafe_inline_in_the_site_wide_policy_is_reported() -> None:
    # Adding it drops the theme script's hash (browsers would ignore it next to
    # a hash), so every inline script would run.
    assert _ids(deploy.check_csp_scripts()) == ["karni.W519"]


@override_settings(**PRODUCTION)
def test_the_middleware_missing_is_reported() -> None:
    from django.conf import settings

    without = [m for m in settings.MIDDLEWARE if m != "karni.security.SecurityHeadersMiddleware"]
    with override_settings(MIDDLEWARE=without):
        assert _ids(deploy.check_csp_present()) == ["karni.W518"]


@override_settings(**PRODUCTION)
def test_production_email_names_each_problem() -> None:
    with override_settings(EMAIL_BACKEND=UNSENT + "console.EmailBackend"):
        (message,) = deploy.check_email()
    assert "the console backend, which prints each email to the log" in message.msg
    assert "DEFAULT_FROM_EMAIL" not in message.msg
    with override_settings(
        EMAIL_BACKEND=UNSENT + "locmem.EmailBackend", DEFAULT_FROM_EMAIL="webmaster@localhost"
    ):
        (message,) = deploy.check_email()
    assert "locmem backend" in message.msg and "'webmaster@localhost'" in message.msg
    assert "EMAIL_URL" in str(message.hint) and "karni.W520" in str(message.hint)


def test_weak_secret_key_follows_djangos_rule() -> None:
    assert deploy.weak_secret_key(STRONG_KEY) is None
    assert deploy.weak_secret_key("") == "SECRET_KEY is empty"
    assert "49 characters" in str(deploy.weak_secret_key("a1b2c3d4e5" * 4 + "a1b2c3d4e"))


def test_every_deploy_code_is_registered() -> None:
    from karni.errorcodes import get

    for number in range(510, 521):
        entry = get(f"W{number}")
        assert entry is not None and entry.kind == "warning"
        assert "(deploy)" in entry.source


# --- the commands -------------------------------------------------------------


def _run(*args: str, **settings: Any) -> tuple[str, str, BaseException | None]:
    out, err = io.StringIO(), io.StringIO()
    raised: BaseException | None = None
    with override_settings(**settings):
        try:
            call_command(*args, stdout=out, stderr=err)
        except Exception as exc:  # noqa: BLE001 - the test inspects it
            raised = exc
    return out.getvalue(), err.getvalue(), raised


def test_manage_py_check_deploy_runs_karnis_checks() -> None:
    _out, err, _raised = _run("check", "--deploy", **DEVELOPMENT)
    for code in ("W510", "W511", "W512", "W513", "W514", "W515", "W516", "W517", "W518", "W520"):
        assert f"karni.{code}" in err
    assert "security.W018" in err  # plain check --deploy keeps Django's own too


def test_plain_check_runs_no_deploy_check() -> None:
    _out, err, _raised = _run("check", **DEVELOPMENT)
    assert "karni.W510" not in err


def test_karni_check_deploy_fails_on_the_development_values() -> None:
    _out, err, raised = _run("karni_check", "--deploy", **DEVELOPMENT)
    assert isinstance(raised, KarniCommandError)
    assert "deploy checks failed" in err
    for code in ("W510", "W511", "W512", "W513", "W514", "W515", "W516", "W517", "W518", "W520"):
        assert f"karni.{code}" in err
    # Each problem once: the Django warnings the Karni checks cover are hidden.
    for django_id in ("security.W018", "security.W009", "security.W004", "security.W012"):
        assert django_id not in err
    assert "HINT: Run production with DJANGO_ENV=prod" in err


def test_silencing_a_karni_check_brings_back_djangos() -> None:
    _out, err, _raised = _run(
        "karni_check",
        "--deploy",
        **DEVELOPMENT,
        SILENCED_SYSTEM_CHECKS=["karni.W510"],
    )
    assert "karni.W510" not in err
    assert "security.W018" in err


def test_superseded_lists_only_unsilenced_karni_checks() -> None:
    from karni.management.commands.karni_check import superseded_django_checks

    with override_settings(SILENCED_SYSTEM_CHECKS=["karni.W515"]):
        hidden = superseded_django_checks()
    assert "security.W018" in hidden
    assert "security.W012" not in hidden
