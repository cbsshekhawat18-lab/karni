# ruff: noqa: E402
"""Tests for :mod:`karni.accounts.twofa` (accounts contract §2FA + amendments A6/A13).

The whole module is skipped when django-otp is not installed (extra
``karni[2fa]``) or its apps are not in ``INSTALLED_APPS``.
"""

from __future__ import annotations

import base64
import time
from typing import Any
from unittest import mock

import pytest
from django.apps import apps

pytest.importorskip("django_otp")
if not (apps.is_installed("django_otp") and apps.is_installed("django_otp.plugins.otp_totp")):
    pytest.skip(
        "django_otp apps are not in INSTALLED_APPS (KARNI_2FA disabled)",
        allow_module_level=True,
    )

from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import cache
from django.test import override_settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.middleware import OTPMiddleware
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework.throttling import SimpleRateThrottle

from karni.accounts import twofa

pytestmark = pytest.mark.django_db

PASSWORD = "totp-pass-123!x"
LOGIN_URL = "/api/auth/login/"

factory = APIRequestFactory()


@pytest.fixture(autouse=True)
def _throttle_and_cache(monkeypatch: pytest.MonkeyPatch) -> Any:
    # The replay guard and DRF throttling both live in the default cache.
    cache.clear()
    for scope in ("auth.login", "auth.login_account", "auth.2fa"):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, "1000/min")
    yield
    cache.clear()


@pytest.fixture
def user(django_user_model: Any) -> Any:
    return django_user_model.objects.create_user(email="twofa@example.com", password=PASSWORD)


def _code(device: Any) -> str:
    """Compute the current TOTP code for *device* the same way an app would."""
    value = totp(
        device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=device.drift
    )
    return f"{value:0{device.digits}d}"


def _reset_replay(device: Any) -> None:
    """Allow the current time-step code to verify again on *device*.

    ``verify_token()`` records the last verified step (replay protection) and
    throttles after failures; tests reset both to reuse a code within one
    30-second window.
    """
    device.refresh_from_db()
    device.last_t = -1
    device.throttle_reset(commit=False)
    device.save()


def _enable_2fa(user: Any) -> Any:
    twofa.setup_totp(user)
    device = TOTPDevice.objects.devices_for_user(user, confirmed=False).get()
    twofa.confirm_totp(user, _code(device))
    _reset_replay(device)
    return device


def _call(view_class: Any, *, user: Any = None, data: dict[str, Any] | None = None) -> Any:
    request = factory.post("/2fa/", data or {}, format="json")
    if user is not None:
        force_authenticate(request, user=user)
    return view_class.as_view()(request)


class TestSetup:
    def test_setup_returns_device_payload(self, user: Any) -> None:
        response = _call(twofa.TwoFASetupView, user=user)
        assert response.status_code == 200
        device = TOTPDevice.objects.devices_for_user(user, confirmed=False).get()
        assert response.data["device_id"] == device.persistent_id
        assert response.data["otpauth_url"] == device.config_url
        assert response.data["otpauth_url"].startswith("otpauth://totp/")
        assert response.data["secret"] == base64.b32encode(device.bin_key).decode("ascii")
        assert not device.confirmed
        assert twofa.user_has_2fa(user) is False

    def test_second_setup_replaces_pending_device(self, user: Any) -> None:
        _call(twofa.TwoFASetupView, user=user)
        _call(twofa.TwoFASetupView, user=user)
        assert TOTPDevice.objects.devices_for_user(user, confirmed=False).count() == 1

    def test_setup_requires_authentication(self) -> None:
        response = _call(twofa.TwoFASetupView)
        assert response.status_code in (401, 403)


class TestConfirmDisable:
    def test_confirm_with_valid_code(self, user: Any) -> None:
        twofa.setup_totp(user)
        device = TOTPDevice.objects.devices_for_user(user, confirmed=False).get()
        response = _call(twofa.TwoFAConfirmView, user=user, data={"code": _code(device)})
        assert response.status_code == 200
        device.refresh_from_db()
        assert device.confirmed
        assert twofa.user_has_2fa(user) is True

    def test_confirm_bad_code(self, user: Any) -> None:
        twofa.setup_totp(user)
        response = _call(twofa.TwoFAConfirmView, user=user, data={"code": "not-a-code"})
        assert response.status_code == 400
        assert response.data["code"] == "invalid_code"
        assert twofa.user_has_2fa(user) is False

    def test_disable_with_valid_code(self, user: Any) -> None:
        device = _enable_2fa(user)
        response = _call(twofa.TwoFADisableView, user=user, data={"code": _code(device)})
        assert response.status_code == 200
        assert TOTPDevice.objects.devices_for_user(user).count() == 0
        assert twofa.user_has_2fa(user) is False

    def test_disable_bad_code_keeps_2fa(self, user: Any) -> None:
        _enable_2fa(user)
        response = _call(twofa.TwoFADisableView, user=user, data={"code": "not-a-code"})
        assert response.status_code == 400
        assert response.data["code"] == "invalid_code"
        assert twofa.user_has_2fa(user) is True


class TestUserHas2FA:
    def test_false_for_anonymous_and_none(self) -> None:
        assert twofa.user_has_2fa(AnonymousUser()) is False
        assert twofa.user_has_2fa(None) is False

    def test_false_without_confirmed_device(self, user: Any) -> None:
        assert twofa.user_has_2fa(user) is False
        twofa.setup_totp(user)  # unconfirmed devices do not count
        assert twofa.user_has_2fa(user) is False


class TestLoginGate:
    def test_login_returns_ephemeral_token_instead_of_credentials(self, user: Any) -> None:
        _enable_2fa(user)
        client = APIClient()
        with override_settings(KARNI_2FA=True):
            response = client.post(
                LOGIN_URL, {"email": user.email, "password": PASSWORD}, format="json"
            )
        assert response.status_code == 200
        assert response.data.get("requires_2fa") is True
        assert response.data.get("ephemeral_token")
        assert "access" not in response.data
        assert "refresh" not in response.data


class TestTwoFALogin:
    def test_jwt_exchange_issues_token_pair(self, user: Any) -> None:
        device = _enable_2fa(user)
        token = twofa.issue_ephemeral_token(user)
        response = _call(
            twofa.TwoFALoginView, data={"ephemeral_token": token, "code": _code(device)}
        )
        assert response.status_code == 200
        assert response.data["access"]
        assert response.data["refresh"]
        assert response.data["user"]["email"] == user.email

    def test_bad_code_does_not_consume_token(self, user: Any) -> None:
        device = _enable_2fa(user)
        token = twofa.issue_ephemeral_token(user)
        response = _call(
            twofa.TwoFALoginView, data={"ephemeral_token": token, "code": "not-a-code"}
        )
        assert response.status_code == 400
        assert response.data["code"] == "invalid_code"
        # The same ephemeral token still works once the right code arrives.
        _reset_replay(device)
        response = _call(
            twofa.TwoFALoginView, data={"ephemeral_token": token, "code": _code(device)}
        )
        assert response.status_code == 200

    def test_replayed_token_rejected(self, user: Any) -> None:
        device = _enable_2fa(user)
        token = twofa.issue_ephemeral_token(user)
        first = _call(twofa.TwoFALoginView, data={"ephemeral_token": token, "code": _code(device)})
        assert first.status_code == 200
        _reset_replay(device)
        second = _call(twofa.TwoFALoginView, data={"ephemeral_token": token, "code": _code(device)})
        assert second.status_code == 401
        assert second.data["code"] == "replayed_token"

    def test_expired_ephemeral_token(self, user: Any) -> None:
        _enable_2fa(user)
        past = time.time() - (twofa.EPHEMERAL_TOKEN_MAX_AGE + 100)
        with mock.patch("django.core.signing.time.time", return_value=past):
            token = twofa.issue_ephemeral_token(user)
        response = _call(twofa.TwoFALoginView, data={"ephemeral_token": token, "code": "000000"})
        assert response.status_code == 401
        assert response.data["code"] == "expired_token"

    def test_tampered_token_rejected(self, user: Any) -> None:
        _enable_2fa(user)
        token = twofa.issue_ephemeral_token(user) + "tampered"
        response = _call(twofa.TwoFALoginView, data={"ephemeral_token": token, "code": "000000"})
        assert response.status_code == 401
        assert response.data["code"] == "invalid_token"

    def test_inactive_user_rejected(self, user: Any) -> None:
        device = _enable_2fa(user)
        token = twofa.issue_ephemeral_token(user)
        user.is_active = False
        user.save(update_fields=["is_active"])
        response = _call(
            twofa.TwoFALoginView, data={"ephemeral_token": token, "code": _code(device)}
        )
        assert response.status_code == 401
        assert response.data["code"] == "invalid_token"

    def test_session_mode_logs_in_and_marks_verified(self, user: Any) -> None:
        # Amendments A6 + A13: session-mode 2fa/login performs auth.login and
        # django_otp.login so OTPMiddleware sees a verified user afterwards.
        device = _enable_2fa(user)
        token = twofa.issue_ephemeral_token(user)
        request = factory.post(
            "/2fa/login/", {"ephemeral_token": token, "code": _code(device)}, format="json"
        )
        SessionMiddleware(lambda r: r).process_request(request)
        with override_settings(KARNI_AUTH_MODE="session"):
            response = twofa.TwoFALoginView.as_view()(request)
        assert response.status_code == 200
        assert response.data["user"]["email"] == user.email
        assert "access" not in response.data
        assert request.session[SESSION_KEY] == str(user.pk)
        assert request.session[DEVICE_ID_SESSION_KEY] == device.persistent_id

        follow_up = factory.get("/")
        follow_up.session = request.session
        follow_up.user = user
        # New-style middleware (django-otp >= 1.4): call it, don't process_request.
        OTPMiddleware(lambda r: r)(follow_up)
        assert follow_up.user.is_verified()
        assert follow_up.user.otp_device.persistent_id == device.persistent_id


class TestServices:
    def test_confirm_totp_raises_without_pending_device(self, user: Any) -> None:
        with pytest.raises(twofa.TwoFAError) as excinfo:
            twofa.confirm_totp(user, "123456")
        assert excinfo.value.code == "invalid_code"

    def test_mark_ephemeral_token_used_is_single_use(self, user: Any) -> None:
        token = twofa.issue_ephemeral_token(user)
        assert twofa.mark_ephemeral_token_used(token) is True
        assert twofa.mark_ephemeral_token_used(token) is False

    def test_resolve_ephemeral_token_roundtrip(self, user: Any) -> None:
        token = twofa.issue_ephemeral_token(user)
        assert twofa.resolve_ephemeral_token(token) == user
