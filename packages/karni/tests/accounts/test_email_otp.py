"""Sign-in with a code sent by email (karni.accounts.otp, experimental).

The codes go through the in-memory accounts email backend, so each test reads
the code a user would type from the outbox. ``on_commit`` callbacks run
inside ``django_capture_on_commit_callbacks(execute=True)``, the way they run
after a real commit.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
from collections.abc import Callable, Iterator, MutableMapping
from datetime import timedelta
from types import ModuleType
from typing import Any

import pytest
import structlog
from django.contrib.auth import SESSION_KEY, get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.urls import include, path
from django.utils import timezone
from pytest_django import DjangoCaptureOnCommitCallbacks, Settings
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from karni.accounts import otp
from karni.accounts.emails import InMemoryEmailBackend
from karni.accounts.models import LoginCode
from karni.accounts.urls import build_urlpatterns
from karni.conf.validation import validate_settings
from karni.errorcodes import get as get_code

pytestmark = pytest.mark.django_db

SEND = "/api/auth/otp/send/"
VERIFY = "/api/auth/otp/verify/"
EMAIL = "ada@example.com"
PASSWORD = "existing-pass-123!x"
SCOPES = ("auth.otp_send", "auth.otp_send_email", "auth.otp_verify")


def _urlconf() -> ModuleType:
    """A URLconf built now: karni.accounts.urls builds its list once, at import."""
    from django.contrib import admin

    module = ModuleType("email_otp_urls")
    module.__dict__["urlpatterns"] = [
        path("admin/", admin.site.urls),
        path("api/auth/", include(build_urlpatterns())),
    ]
    return module


def remount(settings: Settings) -> None:
    settings.ROOT_URLCONF = _urlconf()


@pytest.fixture(autouse=True)
def _otp(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    cache.clear()
    InMemoryEmailBackend.clear()
    settings.KARNI_ACCOUNTS_EMAIL_BACKEND = "karni.accounts.emails.InMemoryEmailBackend"
    settings.KARNI_EMAIL_OTP = True
    settings.KARNI_AUTH_MODE = "jwt"
    for scope in SCOPES:
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, "1000/min")
    remount(settings)
    yield
    InMemoryEmailBackend.clear()
    cache.clear()


@pytest.fixture
def client() -> APIClient:
    return APIClient()


Capture = DjangoCaptureOnCommitCallbacks


def send(client: APIClient, capture: Capture, email: str = EMAIL, **extra: Any) -> Any:
    """``otp/send/``, with the on-commit email delivered as after a real commit."""
    with capture(execute=True):
        return client.post(SEND, {"email": email}, format="json", **extra)


def verify(client: APIClient, code: str, email: str = EMAIL, **extra: Any) -> Any:
    return client.post(VERIFY, {"email": email, "code": code}, format="json", **extra)


def last_code() -> str:
    return str(InMemoryEmailBackend.outbox[-1].context["code"])


def users() -> Any:
    return get_user_model().objects


def assert_refused(response: Any, code: str = "E235", status: int = 401) -> dict[str, Any]:
    assert response.status_code == status, response.content
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    assert body["detail"].startswith(f"{code}: ")
    assert get_code(code) is not None  # karni explain knows it
    assert "access" not in body and "refresh" not in body and "user" not in body
    return body


def assert_signed_in(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.content
    body: dict[str, Any] = response.json()
    assert body["access"] and body["refresh"]
    return body


def reasons(events: list[MutableMapping[str, Any]]) -> list[str]:
    """The ``reason`` of every ``accounts.otp.refused`` event, in order."""
    return [str(e["reason"]) for e in events if e["event"] == "accounts.otp.refused"]


def wrong(code: str) -> str:
    """A code of the same length that is not ``code``."""
    return f"{(int(code) + 1) % 10 ** len(code):0{len(code)}d}"


# routes


def test_the_routes_exist_only_while_the_setting_is_on(settings: Settings) -> None:
    names = {p.name for p in build_urlpatterns() if getattr(p, "name", None)}
    assert {"karni-accounts-otp-send", "karni-accounts-otp-verify"} <= names
    settings.KARNI_EMAIL_OTP = False
    names = {p.name for p in build_urlpatterns() if getattr(p, "name", None)}
    assert not names & {"karni-accounts-otp-send", "karni-accounts-otp-verify"}
    remount(settings)
    client = APIClient()
    assert client.post(SEND, {"email": EMAIL}, format="json").status_code == 404
    assert client.post(VERIFY, {"email": EMAIL, "code": "123456"}, format="json").status_code == 404


def test_the_routes_are_absent_from_the_schema_while_off(settings: Settings) -> None:
    from karni.testing.schema import generate_schema

    def paths() -> set[str]:
        remount(settings)
        return set(generate_schema()["paths"])

    assert {"/api/auth/otp/send/", "/api/auth/otp/verify/"} <= paths()
    settings.KARNI_EMAIL_OTP = False
    assert not {"/api/auth/otp/send/", "/api/auth/otp/verify/"} & paths()


def test_a_urlconf_built_while_on_answers_e236_once_the_setting_is_off(
    settings: Settings, client: APIClient
) -> None:
    settings.KARNI_EMAIL_OTP = False
    assert_refused(client.post(SEND, {"email": EMAIL}, format="json"), "E236", 404)
    assert_refused(verify(client, "123456"), "E236", 404)
    assert not LoginCode.objects.exists()


def test_bad_bodies_are_plain_400s(client: APIClient) -> None:
    response = client.post(SEND, {"email": "not-an-address"}, format="json")
    assert response.status_code == 400 and "email" in response.json()
    response = client.post(VERIFY, {"email": EMAIL}, format="json")
    assert response.status_code == 400 and "code" in response.json()


# send: one answer for every address


def test_send_answers_the_same_for_known_unknown_inactive_deleted_and_closed_addresses(
    settings: Settings,
    client: APIClient,
    django_capture_on_commit_callbacks: Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hashed: list[str] = []
    real_hash = otp.hash_code

    def counting_hash(address: str, code: str) -> str:
        hashed.append(address)
        return real_hash(address, code)

    monkeypatch.setattr(otp, "hash_code", counting_hash)
    users().create_user(email="known@example.com", password=PASSWORD, email_verified=True)
    users().create_user(email="inactive@example.com", is_active=False)
    users().create_user(email="deleted@example.com").delete()
    capture = django_capture_on_commit_callbacks
    answers = [
        send(client, capture, "known@example.com"),
        send(client, capture, "unknown@example.com"),
        send(client, capture, "inactive@example.com"),
        send(client, capture, "deleted@example.com"),
    ]
    settings.KARNI_EMAIL_OTP_SIGNUP = "existing"
    answers.append(send(client, capture, "closed@example.com"))
    bodies = {json.dumps(response.json(), sort_keys=True) for response in answers}
    assert {response.status_code for response in answers} == {200}
    assert len(bodies) == 1
    assert answers[0].json() == {
        "detail": "If this address may sign in, a sign-in code is on its way to it.",
        "length": 6,
        "expires_in": 600,
    }
    # The same work on every path: one HMAC and one stored row per address.
    assert len(hashed) == 5
    assert LoginCode.objects.count() == 5
    # Mail only where a code can be used: an account that is not deleted, or open sign-up.
    assert [email.to for email in InMemoryEmailBackend.outbox] == [
        "known@example.com",
        "unknown@example.com",
        "inactive@example.com",
    ]
    # Nobody is created by sending.
    assert not users().filter(email__in=["unknown@example.com", "closed@example.com"]).exists()


def test_the_email_goes_out_after_commit_through_the_accounts_backend(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        assert client.post(SEND, {"email": EMAIL}, format="json").status_code == 200
    assert InMemoryEmailBackend.outbox == []  # nothing before the commit
    assert len(callbacks) == 1
    callbacks[0]()
    email = InMemoryEmailBackend.outbox[0]
    assert email.template == "login_code" and email.to == EMAIL
    assert set(email.context) == {"code", "ttl_minutes", "user"}
    assert email.context["user"] is None  # a new address has no account yet
    assert email.context["ttl_minutes"] == 10


def test_the_email_context_carries_the_existing_user(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    user = users().create_user(email="Ada@Example.com", first_name="Ada", email_verified=True)
    send(client, django_capture_on_commit_callbacks, "ada@EXAMPLE.com")
    email = InMemoryEmailBackend.outbox[-1]
    assert email.context["user"] == user
    assert email.to == "Ada@example.com"  # the account's own address


def test_the_default_backend_renders_the_login_code_templates(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    from django.core import mail

    settings.KARNI_ACCOUNTS_EMAIL_BACKEND = "karni.accounts.emails.DjangoEmailBackend"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    users().create_user(email=EMAIL, first_name="Ada", email_verified=True)
    send(client, django_capture_on_commit_callbacks)
    message = mail.outbox[-1]
    assert message.subject == "Your sign-in code"
    code = LoginCode.objects.get(email=EMAIL)
    digits = [word for word in message.body.split() if word.isdigit() and len(word) == 6]
    assert digits and otp.code_matches(code.code_hash, EMAIL, digits[0])
    assert "Hi Ada," in message.body and "10 minutes" in message.body
    html = message.alternatives[0][0]
    assert digits[0] in html


def test_a_failing_mail_server_changes_nothing_in_the_answer(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    settings.KARNI_ACCOUNTS_EMAIL_BACKEND = "tests.accounts.test_email_otp.BrokenBackend"
    with structlog.testing.capture_logs() as events:
        response = send(client, django_capture_on_commit_callbacks)
    assert response.status_code == 200
    assert response.json()["length"] == 6
    failed = [event for event in events if event["event"] == "accounts.otp.email_failed"]
    assert failed and failed[0]["error"] == "ConnectionRefusedError"


class BrokenBackend(InMemoryEmailBackend):
    def send(self, email: Any) -> None:
        raise ConnectionRefusedError("the mail server is down")


# the code


def test_the_code_is_never_stored_in_plain_text(
    client: APIClient, django_capture_on_commit_callbacks: Capture, settings: Settings
) -> None:
    send(client, django_capture_on_commit_callbacks)
    code = last_code()
    row = LoginCode.objects.get(email=EMAIL)
    values = [str(value) for value in LoginCode.objects.filter(pk=row.pk).values().get().values()]
    assert not any(code in value for value in values)
    expected = hmac.new(
        settings.SECRET_KEY.encode(),
        b"karni.accounts.login_code\x00" + EMAIL.encode() + b"\x00" + code.encode(),
        hashlib.sha256,
    ).hexdigest()
    assert row.code_hash == expected


def test_the_hash_binds_the_address_and_the_secret_key(settings: Settings) -> None:
    first = otp.hash_code(EMAIL, "123456")
    assert otp.hash_code(" ADA@example.com ", "123456") == first  # normalized
    assert otp.hash_code("grace@example.com", "123456") != first
    settings.SECRET_KEY = "another-secret-key-for-this-test-only"
    assert otp.hash_code(EMAIL, "123456") != first


def test_codes_are_compared_in_constant_time(
    client: APIClient,
    django_capture_on_commit_callbacks: Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    real = hmac.compare_digest

    def spy(a: str, b: str) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(otp.hmac, "compare_digest", spy)
    send(client, django_capture_on_commit_callbacks)
    code = last_code()
    assert_refused(verify(client, wrong(code)))
    assert_signed_in(verify(client, code))
    assert len(calls) == 2
    row = LoginCode.objects.get(email=EMAIL)
    assert all(stored == row.code_hash for stored, _ in calls)
    assert otp.code_matches(row.code_hash, EMAIL, code)


def test_codes_are_uniform_digits_from_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []

    def fake_randbelow(bound: int) -> int:
        seen.append(bound)
        return 42

    monkeypatch.setattr(otp.secrets, "randbelow", fake_randbelow)
    assert otp.generate_code() == "000042"  # leading zeros are kept
    assert otp.generate_code(8) == "00000042"
    assert seen == [10**6, 10**8]
    monkeypatch.undo()
    codes = {otp.generate_code() for _ in range(200)}
    assert all(len(code) == 6 and code.isdigit() for code in codes)
    assert len(codes) > 150


@pytest.mark.parametrize("length", [4, 8, 10])
def test_the_length_setting(
    length: int,
    settings: Settings,
    client: APIClient,
    django_capture_on_commit_callbacks: Capture,
) -> None:
    settings.KARNI_EMAIL_OTP_LENGTH = length
    response = send(client, django_capture_on_commit_callbacks)
    assert response.json()["length"] == length
    code = last_code()
    assert len(code) == length and code.isdigit()
    assert_signed_in(verify(client, code))


def test_the_ttl_setting(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    settings.KARNI_EMAIL_OTP_TTL = 120
    before = timezone.now()
    response = send(client, django_capture_on_commit_callbacks)
    assert response.json()["expires_in"] == 120
    row = LoginCode.objects.get(email=EMAIL)
    assert (
        before + timedelta(seconds=119) <= row.expires_at <= timezone.now() + timedelta(seconds=120)
    )
    assert InMemoryEmailBackend.outbox[-1].context["ttl_minutes"] == 2


def test_whitespace_inside_the_code_is_ignored(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    send(client, django_capture_on_commit_callbacks)
    code = last_code()
    assert_signed_in(verify(client, f" {code[:3]} {code[3:]} ", email=" ADA@example.com "))


# a code dies


def test_an_expired_code_is_refused(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    send(client, django_capture_on_commit_callbacks)
    LoginCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    with structlog.testing.capture_logs() as events:
        assert_refused(verify(client, last_code()))
    assert reasons(events)[-1] == "expired"


def test_a_used_code_is_refused(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    send(client, django_capture_on_commit_callbacks)
    code = last_code()
    assert_signed_in(verify(client, code))
    with structlog.testing.capture_logs() as events:
        assert_refused(verify(client, code))
    assert reasons(events)[-1] == "used"


def test_the_attempt_that_reaches_the_cap_kills_the_code(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    settings.KARNI_EMAIL_OTP_MAX_ATTEMPTS = 3
    send(client, django_capture_on_commit_callbacks)
    code = last_code()
    with structlog.testing.capture_logs() as events:
        for _ in range(3):
            assert_refused(verify(client, wrong(code)))
        assert_refused(verify(client, code))  # right, but too late
    assert reasons(events) == [
        "wrong_code",
        "wrong_code",
        "wrong_code",
        "locked",
    ]
    locked = [event for event in events if event["event"] == "accounts.otp.locked"]
    assert len(locked) == 1 and locked[0]["attempts"] == 3
    assert LoginCode.objects.get(email=EMAIL).attempts == 3


def test_a_right_code_within_the_cap_signs_in(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    settings.KARNI_EMAIL_OTP_MAX_ATTEMPTS = 3
    send(client, django_capture_on_commit_callbacks)
    code = last_code()
    for _ in range(2):
        assert_refused(verify(client, wrong(code)))
    assert_signed_in(verify(client, code))


def test_parallel_guesses_cannot_exceed_the_cap(
    client: APIClient,
    django_capture_on_commit_callbacks: Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send(client, django_capture_on_commit_callbacks)
    code = last_code()

    def other_guesses_land_first() -> int:
        # This guess read the row with no attempt spent. Before it is counted,
        # other requests spend the last ones: the filtered UPDATE decides.
        LoginCode.objects.update(attempts=2)
        return 2

    monkeypatch.setattr(otp, "max_attempts", other_guesses_land_first)
    with structlog.testing.capture_logs() as events:
        assert_refused(verify(client, code))
    assert reasons(events)[-1] == "locked"
    assert LoginCode.objects.get(email=EMAIL).attempts == 2
    assert LoginCode.objects.get(email=EMAIL).used_at is None


def test_a_new_code_cancels_the_old_one(
    client: APIClient,
    django_capture_on_commit_callbacks: Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codes = iter(["111111", "222222"])
    monkeypatch.setattr(otp, "generate_code", lambda length=None: next(codes))
    send(client, django_capture_on_commit_callbacks)
    send(client, django_capture_on_commit_callbacks, "ADA@example.com")
    assert LoginCode.objects.filter(email=EMAIL).count() == 1
    with structlog.testing.capture_logs() as events:
        assert_refused(verify(client, "111111"))
    assert reasons(events)[-1] == "wrong_code"
    assert_signed_in(verify(client, "222222"))


def test_sending_cleans_expired_codes_of_other_addresses(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    send(client, django_capture_on_commit_callbacks, "grace@example.com")
    send(client, django_capture_on_commit_callbacks, "hopper@example.com")
    LoginCode.objects.filter(email="grace@example.com").update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    send(client, django_capture_on_commit_callbacks)
    assert set(LoginCode.objects.values_list("email", flat=True)) == {
        "hopper@example.com",
        EMAIL,
    }


def test_every_failure_is_the_same_refusal(
    settings: Settings,
    client: APIClient,
    django_capture_on_commit_callbacks: Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = django_capture_on_commit_callbacks
    monkeypatch.setattr(otp, "generate_code", lambda length=None: "246810")
    settings.KARNI_EMAIL_OTP_MAX_ATTEMPTS = 1
    users().create_user(email="deleted@example.com").delete()
    bodies: dict[str, dict[str, Any]] = {}
    send(client, capture, "wrong@example.com")
    bodies["wrong_code"] = assert_refused(verify(client, "135791", "wrong@example.com"))
    bodies["locked"] = assert_refused(verify(client, "246810", "wrong@example.com"))
    send(client, capture, "expired@example.com")
    LoginCode.objects.filter(email="expired@example.com").update(expires_at=timezone.now())
    bodies["expired"] = assert_refused(verify(client, "246810", "expired@example.com"))
    send(client, capture, "used@example.com")
    assert_signed_in(verify(client, "246810", "used@example.com"))
    bodies["used"] = assert_refused(verify(client, "246810", "used@example.com"))
    bodies["no_code"] = assert_refused(verify(client, "246810", "nobody@example.com"))
    send(client, capture, "deleted@example.com")  # no email: nobody can have the code
    bodies["deleted"] = assert_refused(verify(client, "246810", "deleted@example.com"))
    settings.KARNI_EMAIL_OTP_SIGNUP = "existing"
    send(client, capture, "closed@example.com")
    bodies["signup_closed"] = assert_refused(verify(client, "246810", "closed@example.com"))
    assert len({json.dumps(body, sort_keys=True) for body in bodies.values()}) == 1
    assert not users().filter(email="closed@example.com").exists()


# who signs in


def test_open_creates_a_verified_account_with_the_default_roles(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    from django.contrib.auth.models import Group

    Group.objects.get_or_create(name="attendee")
    settings.KARNI_ACCOUNTS_DEFAULT_ROLES = ["attendee"]
    send(client, django_capture_on_commit_callbacks, "Ada@Example.com")
    assert not users().filter(email__iexact=EMAIL).exists()  # not at send time
    body = assert_signed_in(verify(client, last_code(), "Ada@Example.com"))
    user = users().get(email__iexact=EMAIL)
    assert user.email == "Ada@example.com"  # the domain lower-cased, as create_user does
    assert user.email_verified is True and user.is_active is True
    assert not user.has_usable_password()
    assert body["user"]["roles"] == ["attendee"]
    assert LoginCode.objects.get(email=EMAIL).used_at is not None


def test_an_existing_account_signs_in_and_its_address_becomes_verified(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    user = users().create_user(email=EMAIL, password=PASSWORD, email_verified=True)
    send(client, django_capture_on_commit_callbacks)
    assert LoginCode.objects.get(email=EMAIL).user == user
    body = assert_signed_in(verify(client, last_code()))
    assert body["user"]["id"] == str(user.pk)
    assert "password_removed" not in body
    user.refresh_from_db()
    assert user.check_password(PASSWORD)  # a verified account keeps its password
    assert users().count() == 1


def test_an_unverified_account_is_verified_and_loses_a_password_someone_else_may_know(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
    from rest_framework_simplejwt.tokens import RefreshToken

    user = users().create_user(email=EMAIL, password=PASSWORD)
    RefreshToken.for_user(user)
    send(client, django_capture_on_commit_callbacks)
    body = assert_signed_in(verify(client, last_code()))
    assert body["password_removed"] is True  # the app can tell the person
    user.refresh_from_db()
    assert user.email_verified is True
    assert not user.has_usable_password()
    assert BlacklistedToken.objects.filter(token__user=user).exists()


def test_approval_creates_an_inactive_account_and_signs_nothing_in(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    settings.KARNI_AUTH_MODE = "session"
    settings.KARNI_EMAIL_OTP_SIGNUP = "approval"
    send(client, django_capture_on_commit_callbacks)
    body = assert_refused(verify(client, last_code()), "E224", 202)
    assert body["awaiting_approval"] is True
    user = users().get(email=EMAIL)
    assert user.is_active is False and user.email_verified is True
    assert SESSION_KEY not in client.session
    # A later code for the inactive account: refused as inactive, after the right code.
    send(client, django_capture_on_commit_callbacks)
    assert_refused(verify(client, last_code()), "E226", 401)
    # An administrator activates the account: the next code signs in.
    user.is_active = True
    user.save(update_fields=["is_active"])
    send(client, django_capture_on_commit_callbacks)
    response = verify(client, last_code())
    assert response.status_code == 200
    assert client.session[SESSION_KEY] == str(user.pk)


def test_approval_lets_an_existing_account_in(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    settings.KARNI_EMAIL_OTP_SIGNUP = "approval"
    users().create_user(email=EMAIL, email_verified=True)
    send(client, django_capture_on_commit_callbacks)
    assert_signed_in(verify(client, last_code()))


def test_existing_sends_no_code_to_an_unknown_address_and_lets_accounts_in(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    settings.KARNI_EMAIL_OTP_SIGNUP = "existing"
    assert send(client, django_capture_on_commit_callbacks).status_code == 200
    assert InMemoryEmailBackend.outbox == []
    users().create_user(email=EMAIL, email_verified=True)
    send(client, django_capture_on_commit_callbacks)
    assert_signed_in(verify(client, last_code()))


def test_a_policy_closed_after_the_send_creates_nobody(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    send(client, django_capture_on_commit_callbacks)
    settings.KARNI_EMAIL_OTP_SIGNUP = "existing"
    with structlog.testing.capture_logs() as events:
        assert_refused(verify(client, last_code()))
    assert reasons(events)[-1] == "signup_closed"
    assert not users().filter(email=EMAIL).exists()


def test_the_default_policy_follows_registration(settings: Settings) -> None:
    settings.KARNI_EMAIL_OTP_SIGNUP = None
    settings.KARNI_ACCOUNTS_REGISTRATION = True
    assert otp.signup_policy() == "open"
    settings.KARNI_ACCOUNTS_REGISTRATION = False
    assert otp.signup_policy() == "existing"
    settings.KARNI_EMAIL_OTP_SIGNUP = "approval"
    assert otp.signup_policy() == "approval"
    # Each flow reads its own setting.
    settings.KARNI_SOCIAL_TOKEN_SIGNUP = "open"
    assert otp.signup_policy() == "approval"


def test_closed_registration_closes_sign_up_by_code_too(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    settings.KARNI_ACCOUNTS_REGISTRATION = False
    send(client, django_capture_on_commit_callbacks)
    assert InMemoryEmailBackend.outbox == []


def test_an_inactive_user_never_signs_in(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    user = users().create_user(email=EMAIL, is_active=False, email_verified=False)
    send(client, django_capture_on_commit_callbacks)
    assert_refused(verify(client, last_code()), "E226", 401)
    user.refresh_from_db()
    assert user.email_verified is False  # an inactive account is left as it is


def test_an_account_deactivated_after_the_send_never_signs_in(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    users().create_user(email=EMAIL, email_verified=True)
    send(client, django_capture_on_commit_callbacks)
    users().filter(email=EMAIL).update(is_active=False)
    assert_refused(verify(client, last_code()), "E226", 401)


def test_an_account_deleted_after_the_send_never_signs_in(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    users().create_user(email=EMAIL, email_verified=True)
    send(client, django_capture_on_commit_callbacks)
    users().get(email=EMAIL).delete()
    with structlog.testing.capture_logs() as events:
        assert_refused(verify(client, last_code()))
    assert reasons(events)[-1] == "deleted"
    assert users().without("soft_delete", reason="test").filter(email=EMAIL).count() == 1


def test_an_account_opened_between_send_and_verify_is_signed_in(
    client: APIClient, django_capture_on_commit_callbacks: Capture, monkeypatch: pytest.MonkeyPatch
) -> None:
    send(client, django_capture_on_commit_callbacks)
    real_create = otp._create

    def racing_create(email: str, *, active: bool) -> Any:
        users().create_user(email=EMAIL, email_verified=True)  # another request wins
        return real_create(email, active=active)

    monkeypatch.setattr(otp, "_create", racing_create)
    assert_signed_in(verify(client, last_code()))
    assert users().filter(email__iexact=EMAIL).count() == 1


# the login/ contract: modes, 2FA


def test_jwt_mode_tokens_authenticate(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    send(client, django_capture_on_commit_callbacks)
    body = assert_signed_in(verify(client, last_code()))
    assert body["user"]["email"] == EMAIL
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
    me = client.get("/api/auth/me/")
    assert me.status_code == 200 and me.json()["email"] == EMAIL


def test_session_mode_opens_a_session(
    settings: Settings, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    settings.KARNI_AUTH_MODE = "session"
    send(client, django_capture_on_commit_callbacks)
    response = verify(client, last_code())
    assert response.status_code == 200
    body = response.json()
    assert "access" not in body and body["user"]["email"] == EMAIL
    assert client.session[SESSION_KEY] == body["user"]["id"]
    assert "csrftoken" in response.cookies
    assert client.get("/api/auth/me/").json()["email"] == EMAIL


def test_the_2fa_gate_withholds_credentials(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    client: APIClient,
    django_capture_on_commit_callbacks: Capture,
) -> None:
    from karni.accounts import twofa

    settings.KARNI_2FA = True
    monkeypatch.setattr(twofa, "user_has_2fa", lambda user: True)
    user = users().create_user(email=EMAIL, email_verified=True)
    send(client, django_capture_on_commit_callbacks)
    response = verify(client, last_code())
    assert response.status_code == 200
    body = response.json()
    assert body["requires_2fa"] is True and body["ephemeral_token"]
    assert "access" not in body and "user" not in body
    assert twofa.resolve_ephemeral_token(body["ephemeral_token"]) == user


# throttles


def test_send_is_throttled_per_ip(
    monkeypatch: pytest.MonkeyPatch, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth.otp_send", "2/hour")
    capture = django_capture_on_commit_callbacks
    for index in range(2):
        assert send(client, capture, f"user{index}@example.com").status_code == 200
    assert send(client, capture, "user9@example.com").status_code == 429
    assert send(client, capture, "user9@example.com", REMOTE_ADDR="10.0.0.9").status_code == 200


def test_send_is_throttled_per_address_whatever_the_ip(
    monkeypatch: pytest.MonkeyPatch, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth.otp_send_email", "2/hour")
    capture = django_capture_on_commit_callbacks
    assert send(client, capture, EMAIL, REMOTE_ADDR="10.0.0.1").status_code == 200
    assert send(client, capture, "ADA@example.com", REMOTE_ADDR="10.0.0.2").status_code == 200
    assert send(client, capture, EMAIL, REMOTE_ADDR="10.0.0.3").status_code == 429
    # An address without an account is counted the same way: a 429 says nothing.
    assert send(client, capture, "nobody@example.com", REMOTE_ADDR="10.0.0.4").status_code == 200
    assert len(InMemoryEmailBackend.outbox) == 3


def test_verify_is_throttled_per_ip(monkeypatch: pytest.MonkeyPatch, client: APIClient) -> None:
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth.otp_verify", "2/min")
    for _ in range(2):
        assert verify(client, "000000").status_code == 401
    assert verify(client, "000000").status_code == 429
    assert verify(client, "000000", REMOTE_ADDR="10.0.0.5").status_code == 401


def test_the_throttle_defaults_are_documented() -> None:
    from karni.accounts.api.throttles import DEFAULT_AUTH_THROTTLE_RATES
    from karni.conf.base import AUTH_THROTTLE_DEFAULTS

    expected = {
        "auth.otp_send": "10/hour",
        "auth.otp_send_email": "5/hour",
        "auth.otp_verify": "20/min",
    }
    for scope, rate in expected.items():
        assert DEFAULT_AUTH_THROTTLE_RATES[scope] == rate
        assert AUTH_THROTTLE_DEFAULTS[scope] == rate


# events


def test_security_events_never_carry_the_address_or_the_code(
    client: APIClient, django_capture_on_commit_callbacks: Capture, settings: Settings
) -> None:
    from karni.accounts.api.views import email_fingerprint

    settings.KARNI_EMAIL_OTP_MAX_ATTEMPTS = 1
    with structlog.testing.capture_logs() as events:
        send(client, django_capture_on_commit_callbacks)
        code = last_code()
        verify(client, wrong(code))  # wrong, and the cap: locked
        send(client, django_capture_on_commit_callbacks)
        code2 = last_code()
        verify(client, code2)  # verified, created
    names = [event["event"] for event in events]
    assert names.count("accounts.otp.sent") == 2
    assert "accounts.otp.locked" in names
    assert "accounts.otp.created" in names
    verified = [event for event in events if event["event"] == "accounts.otp.verified"]
    assert len(verified) == 1 and verified[0]["created"] is True
    refused = [event for event in events if event["event"] == "accounts.otp.refused"]
    assert [event["reason"] for event in refused] == ["wrong_code"]
    assert refused[0]["email"] == email_fingerprint(EMAIL)
    dumped = json.dumps(events, default=str)
    for secret in (EMAIL, code, code2, wrong(code)):
        assert secret not in dumped


# cleanup


def test_flush_removes_only_expired_codes(
    client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    from karni.accounts.tasks import flush_login_codes

    send(client, django_capture_on_commit_callbacks)
    send(client, django_capture_on_commit_callbacks, "grace@example.com")
    LoginCode.objects.filter(email="grace@example.com").update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    LoginCode.objects.create(
        email="gone@example.com",
        code_hash="0" * 64,
        expires_at=timezone.now() - timedelta(days=1),
    ).delete()  # soft-deleted rows go too
    assert flush_login_codes() == {"login_codes_deleted": 2}
    alive = LoginCode.objects.without("soft_delete", reason="test").values_list("email", flat=True)
    assert list(alive) == [EMAIL]


def _declared_schedules(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Run karni/accounts/schedules.py again into a fresh registry, as discovery would."""
    from karni import schedule

    fresh = schedule.ScheduleRegistry()
    monkeypatch.setattr(schedule, "_default_registry", fresh)
    from karni.accounts import schedules

    importlib.reload(schedules)
    return [entry.name for entry in fresh.entries()]


def test_the_hourly_cleanup_is_declared_only_while_the_setting_is_on(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _declared_schedules(monkeypatch) == ["karni-flush-login-codes"]
    from karni import schedule

    entry = schedule._default_registry.entries()[0]
    assert entry.task == "karni.accounts.tasks.flush_login_codes"
    assert entry.as_beat_entry()["schedule"] == timedelta(hours=1)
    settings.KARNI_EMAIL_OTP = False
    assert _declared_schedules(monkeypatch) == []


# startup validation


def _validation_error(make_settings: Callable[..., Any], **overrides: Any) -> str:
    ns = make_settings("dev", DEBUG=True, **overrides)
    with pytest.raises(ImproperlyConfigured) as error:
        validate_settings(ns)
    return str(error.value)


def test_the_defaults_and_the_bounds_validate(make_settings: Callable[..., Any]) -> None:
    validate_settings(make_settings("dev", DEBUG=True, KARNI_EMAIL_OTP=True))
    validate_settings(
        make_settings(
            "dev",
            DEBUG=True,
            KARNI_EMAIL_OTP=True,
            KARNI_EMAIL_OTP_TTL=3600,
            KARNI_EMAIL_OTP_LENGTH=4,
            KARNI_EMAIL_OTP_MAX_ATTEMPTS=10,
            KARNI_EMAIL_OTP_SIGNUP="approval",
        )
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"KARNI_EMAIL_OTP": "yes"}, "KARNI_EMAIL_OTP = 'yes' must be True or False"),
        (
            {"KARNI_EMAIL_OTP_TTL": 30},
            "KARNI_EMAIL_OTP_TTL = 30 must be an integer from 60 to 3600",
        ),
        ({"KARNI_EMAIL_OTP_TTL": 86400}, "from 60 to 3600 (seconds a code lives)"),
        (
            {"KARNI_EMAIL_OTP_LENGTH": 3},
            "KARNI_EMAIL_OTP_LENGTH = 3 must be an integer from 4 to 10",
        ),
        ({"KARNI_EMAIL_OTP_LENGTH": 11}, "from 4 to 10 (digits in a code)"),
        ({"KARNI_EMAIL_OTP_LENGTH": "6"}, "KARNI_EMAIL_OTP_LENGTH = '6' must be an integer"),
        ({"KARNI_EMAIL_OTP_MAX_ATTEMPTS": 0}, "KARNI_EMAIL_OTP_MAX_ATTEMPTS = 0 must be"),
        ({"KARNI_EMAIL_OTP_MAX_ATTEMPTS": True}, "KARNI_EMAIL_OTP_MAX_ATTEMPTS = True must be"),
        ({"KARNI_EMAIL_OTP_SIGNUP": "everyone"}, "must be 'open', 'approval', 'existing' or None"),
    ],
)
def test_startup_validation(
    make_settings: Callable[..., Any], overrides: dict[str, Any], expected: str
) -> None:
    message = _validation_error(make_settings, **overrides)
    assert "E504" in message and expected in message


def test_each_setting_reads_its_environment_variable() -> None:
    from karni.conf.reference import settings as documented

    rows = {row.name: row for row in documented()}
    for name in (
        "KARNI_EMAIL_OTP",
        "KARNI_EMAIL_OTP_TTL",
        "KARNI_EMAIL_OTP_LENGTH",
        "KARNI_EMAIL_OTP_MAX_ATTEMPTS",
        "KARNI_EMAIL_OTP_SIGNUP",
    ):
        assert rows[name].env == name
        assert rows[name].description.startswith("Experimental. ")


def test_off_by_default(make_settings: Callable[..., Any]) -> None:
    ns = make_settings("dev", DEBUG=True)
    assert ns["KARNI_EMAIL_OTP"] is False
    assert ns["KARNI_EMAIL_OTP_TTL"] == 600 and ns["KARNI_EMAIL_OTP_LENGTH"] == 6
    assert ns["KARNI_EMAIL_OTP_MAX_ATTEMPTS"] == 5 and ns["KARNI_EMAIL_OTP_SIGNUP"] is None


def test_every_code_is_registered() -> None:
    for code in ("E235", "E236", "E224", "E226"):
        entry = get_code(code)
        assert entry is not None and entry.kind == "api", code
    assert "otp" in get_code("E224").source and "otp" in get_code("E226").source  # type: ignore[union-attr]


# the admin and the permission matrix


def test_the_admin_shows_codes_read_only_without_the_hash(
    admin_client: Any, client: APIClient, django_capture_on_commit_callbacks: Capture
) -> None:
    from django.contrib import admin

    send(client, django_capture_on_commit_callbacks)
    row = LoginCode.objects.get(email=EMAIL)
    model_admin = admin.site._registry[LoginCode]
    request = type("R", (), {"user": users().filter(is_superuser=True).first()})()
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False
    page = admin_client.get("/admin/karni_accounts/logincode/")
    assert page.status_code == 200
    html = page.content.decode()
    assert EMAIL in html and row.code_hash not in html
    detail = admin_client.get(f"/admin/karni_accounts/logincode/{row.pk}/change/")
    assert detail.status_code == 200 and row.code_hash not in detail.content.decode()


def test_login_codes_stay_out_of_the_permission_matrix(settings: Settings) -> None:
    from karni.accounts.matrix import DEFAULT_MATRIX_EXCLUDE

    assert "karni_accounts.LoginCode" in DEFAULT_MATRIX_EXCLUDE
    assert "karni_accounts.LoginCode" in settings.KARNI_MATRIX_EXCLUDE
