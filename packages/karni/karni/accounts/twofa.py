"""Two-factor authentication (TOTP) for :mod:`karni.accounts`.

Services, DRF views and a :data:`urlpatterns` list implementing the Karni 2FA
flow (accounts contract §2FA + amendments A5/A6). ``karni/accounts/urls.py``
mounts :data:`urlpatterns` under ``2fa/`` when ``KARNI_2FA`` is enabled, so a
project mounting the accounts URLs at ``api/auth/`` gets::

    POST /api/auth/2fa/setup/    provision an unconfirmed TOTP device (auth required)
    POST /api/auth/2fa/confirm/  confirm it with a first code (auth required)
    POST /api/auth/2fa/disable/  drop 2FA, requires a valid code (auth required)
    POST /api/auth/2fa/login/    exchange {ephemeral_token, code} for credentials

django-otp is an optional dependency (``pip install 'karni[2fa]'``) and is only
imported lazily inside the functions that need it.

Security posture (amendment A6):

* The ephemeral login token is a salted :class:`~django.core.signing.TimestampSigner`
  signature of the user's primary key (salt ``karni.accounts.2fa``, max age
  :data:`EPHEMERAL_TOKEN_MAX_AGE` seconds).
* A successful exchange is single-use: a default-cache guard
  (``cache.add("karni:2fa:used:<sha256>", ...)``) rejects replays with 401.
* TOTP codes are only ever checked through ``device.verify_token()`` so
  django-otp's replay protection and per-device throttling always apply.
* ``django_otp.middleware.OTPMiddleware`` is wired by ``karni.conf`` in
  session mode only; session-mode 2FA login calls ``django_otp.login()`` so
  the session is marked verified.

Override / escape hatch: every service is a plain module-level function —
subclass the views (or declare your own URL before including
``karni.accounts.urls``; first match wins) and call your own functions.
Throttle rates come from ``KARNI_AUTH_THROTTLE_RATES`` via the merged DRF
``DEFAULT_THROTTLE_RATES`` (scopes ``auth.2fa`` and ``auth.login_account``);
setting a rate to ``None`` disables that throttle.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth import login as django_login
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.urls import path
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from karni.accounts.api.throttles import AccountRateThrottle, AuthScopedRateThrottle
from karni.exceptions import KarniImproperlyConfigured

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser
    from rest_framework.request import Request

__all__ = [
    "EPHEMERAL_TOKEN_MAX_AGE",
    "EPHEMERAL_TOKEN_SALT",
    "TwoFAAccountRateThrottle",
    "TwoFAConfirmView",
    "TwoFADisableView",
    "TwoFAError",
    "TwoFALoginView",
    "TwoFASetupView",
    "confirm_totp",
    "disable_totp",
    "issue_ephemeral_token",
    "mark_ephemeral_token_used",
    "resolve_ephemeral_token",
    "setup_totp",
    "urlpatterns",
    "user_has_2fa",
    "verify_totp_code",
]

EPHEMERAL_TOKEN_SALT = "karni.accounts.2fa"
"""Signer salt binding ephemeral tokens to the 2FA purpose (amendment A6)."""

EPHEMERAL_TOKEN_MAX_AGE = 300
"""Ephemeral 2FA login token lifetime in seconds.

Override / escape hatch: subclass :class:`TwoFALoginView` (or call
:func:`resolve_ephemeral_token` with your own wrapper) if a project needs a
different window; the value is deliberately short and not settings-driven.
"""

_REPLAY_CACHE_PREFIX = "karni:2fa:used:"


class TwoFAError(Exception):
    """A 2FA operation failed.

    ``code`` is a machine-readable reason: ``invalid_code``, ``invalid_token``,
    ``expired_token`` or ``replayed_token``. The exception message is a
    human-readable detail safe to return to API clients.
    """

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def _require_django_otp() -> Any:
    """Import and return the ``django_otp`` package, failing loudly when absent."""
    try:
        import django_otp
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise KarniImproperlyConfigured(
            "Two-factor authentication requires django-otp. "
            "Install it with `pip install 'karni[2fa]'` and enable KARNI_2FA.",
            code="E501",
        ) from exc
    return django_otp


def _totp_device_model() -> Any:
    """Return the ``TOTPDevice`` model class (lazy django-otp import)."""
    _require_django_otp()
    from django_otp.plugins.otp_totp.models import TOTPDevice

    return TOTPDevice


# Services


def user_has_2fa(user: AbstractBaseUser | None) -> bool:
    """Return ``True`` when *user* has at least one confirmed TOTP device.

    Anonymous users, ``None`` and installations without ``django_otp`` in
    ``INSTALLED_APPS`` always yield ``False``, so login views may call this
    unconditionally as the 2FA gate.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not apps.is_installed("django_otp"):
        return False
    device_model = _totp_device_model()
    return device_model.objects.devices_for_user(user, confirmed=True).exists()


def setup_totp(user: AbstractBaseUser) -> dict[str, str]:
    """Provision a new unconfirmed TOTP device for *user*.

    Any previous unconfirmed devices are discarded so at most one pending
    setup exists. Returns ``{"device_id", "otpauth_url", "secret"}`` — the
    ``otpauth_url`` renders as a QR code and ``secret`` is the base32 key for
    manual entry. The device only counts towards :func:`user_has_2fa` once
    :func:`confirm_totp` succeeds.
    """
    device_model = _totp_device_model()
    device_model.objects.devices_for_user(user, confirmed=False).delete()
    device = device_model.objects.create(user=user, name="default", confirmed=False)
    return {
        "device_id": device.persistent_id,
        "otpauth_url": device.config_url,
        "secret": base64.b32encode(device.bin_key).decode("ascii"),
    }


def confirm_totp(user: AbstractBaseUser, code: str) -> Any:
    """Confirm the pending TOTP device for *user* with a first valid *code*.

    Verification goes through ``device.verify_token()`` (django-otp replay
    protection + throttling — amendment A6). On success the device is marked
    confirmed, stale unconfirmed devices are removed and the device is
    returned; otherwise :class:`TwoFAError` (``invalid_code``) is raised.
    """
    device_model = _totp_device_model()
    for device in device_model.objects.devices_for_user(user, confirmed=False):
        if device.verify_token(code):
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            device_model.objects.devices_for_user(user, confirmed=False).delete()
            return device
    raise TwoFAError("invalid_code", "The provided two-factor code is not valid.")


def verify_totp_code(user: AbstractBaseUser, code: str) -> Any:
    """Verify *code* against the user's confirmed TOTP devices.

    Returns the matching device or raises :class:`TwoFAError`
    (``invalid_code``). Always uses ``device.verify_token()`` — never manual
    TOTP math (amendment A6).
    """
    device_model = _totp_device_model()
    for device in device_model.objects.devices_for_user(user, confirmed=True):
        if device.verify_token(code):
            return device
    raise TwoFAError("invalid_code", "The provided two-factor code is not valid.")


def disable_totp(user: AbstractBaseUser, code: str) -> None:
    """Disable 2FA for *user* after verifying *code* against a confirmed device.

    All of the user's TOTP devices (confirmed and pending) are deleted.
    Raises :class:`TwoFAError` (``invalid_code``) on a bad code, leaving 2FA
    enabled.
    """
    device_model = _totp_device_model()
    verify_totp_code(user, code)
    device_model.objects.devices_for_user(user).delete()


# Ephemeral login token (amendment A6)


def _signer() -> TimestampSigner:
    return TimestampSigner(salt=EPHEMERAL_TOKEN_SALT)


def issue_ephemeral_token(user: AbstractBaseUser) -> str:
    """Sign the user's primary key into a short-lived 2FA login token.

    The login view returns this instead of credentials when the user has 2FA
    enabled; ``2fa/login/`` exchanges it (together with a TOTP code) for real
    credentials. Valid for :data:`EPHEMERAL_TOKEN_MAX_AGE` seconds and
    single-use on successful exchange.
    """
    return _signer().sign(str(user.pk))


def resolve_ephemeral_token(token: str) -> AbstractBaseUser:
    """Return the active user an ephemeral 2FA *token* was issued for.

    Does **not** consume the token — call :func:`mark_ephemeral_token_used`
    after the TOTP code verifies, so a mistyped code does not burn the token.
    Raises :class:`TwoFAError` with code ``expired_token`` or
    ``invalid_token``.
    """
    try:
        raw_pk = _signer().unsign(token, max_age=EPHEMERAL_TOKEN_MAX_AGE)
    except SignatureExpired as exc:
        raise TwoFAError("expired_token", "The two-factor login token has expired.") from exc
    except BadSignature as exc:
        raise TwoFAError("invalid_token", "The two-factor login token is not valid.") from exc
    user_model = get_user_model()
    try:
        user = user_model.objects.get(pk=raw_pk)
    except (user_model.DoesNotExist, DjangoValidationError, TypeError, ValueError) as exc:
        raise TwoFAError("invalid_token", "The two-factor login token is not valid.") from exc
    if not user.is_active:
        raise TwoFAError("invalid_token", "The two-factor login token is not valid.")
    return user


def mark_ephemeral_token_used(token: str) -> bool:
    """Single-use guard for a successful ephemeral-token exchange.

    Uses an atomic ``cache.add`` on the default cache (Redis in production via
    ``karni.conf``). Returns ``False`` when the token was already exchanged —
    the caller must treat that as a replay and respond 401 (amendment A6).
    """
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return bool(cache.add(f"{_REPLAY_CACHE_PREFIX}{digest}", 1, EPHEMERAL_TOKEN_MAX_AGE))


# Throttling (amendment A5)


class TwoFAAccountRateThrottle(AccountRateThrottle):
    """Per-account throttle for ``2fa/login/`` (scope ``auth.login_account``).

    Extends the login endpoints' :class:`~karni.accounts.api.throttles.
    AccountRateThrottle` (amendment A5): when the body carries no ``email`` —
    ``2fa/login/`` posts ``{ephemeral_token, code}`` — the identity falls back
    to a hash of the posted ``ephemeral_token``, so TOTP code guessing is
    bounded per issued token no matter how many source IPs are used.

    Override / escape hatch: same as the base class — the rate comes from
    ``KARNI_AUTH_THROTTLE_RATES["auth.login_account"]`` (``None`` disables),
    and :meth:`get_account_ident` is the identity hook.
    """

    def get_account_ident(self, request: Request) -> str | None:
        ident = super().get_account_ident(request)
        if ident is not None:
            return ident
        data = request.data
        if not isinstance(data, Mapping):
            return None
        token = data.get("ephemeral_token")
        if not isinstance(token, str) or not token:
            return None
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Serializers


class TwoFACodeSerializer(serializers.Serializer):
    """Request body for ``2fa/confirm/`` and ``2fa/disable/``."""

    code = serializers.CharField(max_length=32, trim_whitespace=True)


class TwoFALoginSerializer(serializers.Serializer):
    """Request body for ``2fa/login/``."""

    ephemeral_token = serializers.CharField(max_length=512, trim_whitespace=True)
    code = serializers.CharField(max_length=32, trim_whitespace=True)


class TwoFASetupResponseSerializer(serializers.Serializer):
    """Response body for ``2fa/setup/``."""

    device_id = serializers.CharField()
    otpauth_url = serializers.CharField()
    secret = serializers.CharField()


class TwoFADetailSerializer(serializers.Serializer):
    """Generic ``{"detail": ...}`` response body."""

    detail = serializers.CharField()


# Views


def _error_response(exc: TwoFAError, status_code: int) -> Response:
    return Response({"detail": str(exc), "code": exc.code}, status=status_code)


class TwoFASetupView(APIView):
    """POST ``2fa/setup/`` — provision an unconfirmed TOTP device.

    Override / escape hatch: subclass and override :meth:`post`, or declare
    your own URL for ``2fa/setup/`` before including ``karni.accounts.urls``.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthScopedRateThrottle]
    throttle_scope = "auth.2fa"

    @extend_schema(request=None, responses=TwoFASetupResponseSerializer)
    def post(self, request: Request) -> Response:
        return Response(setup_totp(request.user))


class TwoFAConfirmView(APIView):
    """POST ``2fa/confirm/`` ``{code}`` — confirm the pending TOTP device."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthScopedRateThrottle]
    throttle_scope = "auth.2fa"

    @extend_schema(request=TwoFACodeSerializer, responses=TwoFADetailSerializer)
    def post(self, request: Request) -> Response:
        serializer = TwoFACodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            confirm_totp(request.user, serializer.validated_data["code"])
        except TwoFAError as exc:
            return _error_response(exc, status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Two-factor authentication enabled."})


class TwoFADisableView(APIView):
    """POST ``2fa/disable/`` ``{code}`` — disable 2FA after a valid code."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthScopedRateThrottle]
    throttle_scope = "auth.2fa"

    @extend_schema(request=TwoFACodeSerializer, responses=TwoFADetailSerializer)
    def post(self, request: Request) -> Response:
        serializer = TwoFACodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            disable_totp(request.user, serializer.validated_data["code"])
        except TwoFAError as exc:
            return _error_response(exc, status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Two-factor authentication disabled."})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class TwoFALoginView(APIView):
    """POST ``2fa/login/`` ``{ephemeral_token, code}`` — finish a 2FA login.

    The mode is read from ``settings.KARNI_AUTH_MODE`` at request time
    (amendment A3): ``jwt`` issues a SimpleJWT token pair, ``session`` logs the
    user in (including ``django_otp.login`` so ``OTPMiddleware`` marks the
    session verified — amendment A6). Both responses embed the ``MeSerializer``
    payload under ``"user"``.

    Error mapping: bad/expired/replayed ephemeral token → 401 (the code was
    never checked, or the token was already exchanged); bad TOTP code → 400
    (the token stays valid so the user may retry).
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthScopedRateThrottle, TwoFAAccountRateThrottle]
    throttle_scope = "auth.2fa"

    @extend_schema(request=TwoFALoginSerializer, responses=TwoFADetailSerializer)
    def post(self, request: Request) -> Response:
        serializer = TwoFALoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token: str = serializer.validated_data["ephemeral_token"]
        code: str = serializer.validated_data["code"]

        try:
            user = resolve_ephemeral_token(token)
        except TwoFAError as exc:
            return _error_response(exc, status.HTTP_401_UNAUTHORIZED)
        try:
            device = verify_totp_code(user, code)
        except TwoFAError as exc:
            return _error_response(exc, status.HTTP_400_BAD_REQUEST)
        if not mark_ephemeral_token_used(token):
            replay = TwoFAError(
                "replayed_token", "The two-factor login token has already been used."
            )
            return _error_response(replay, status.HTTP_401_UNAUTHORIZED)

        from karni.accounts.api.serializers import MeSerializer

        me_data = MeSerializer(user, context={"request": request}).data

        if getattr(settings, "KARNI_AUTH_MODE", "jwt") == "session":
            django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            django_otp = _require_django_otp()
            django_otp.login(request, device)
            return Response({"user": me_data})

        from rest_framework_simplejwt.settings import api_settings as simplejwt_settings
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        if simplejwt_settings.UPDATE_LAST_LOGIN:
            from django.contrib.auth.models import update_last_login

            update_last_login(None, user)  # type: ignore[arg-type]
        return Response(
            {"access": str(refresh.access_token), "refresh": str(refresh), "user": me_data}
        )


urlpatterns = [
    path("setup/", TwoFASetupView.as_view(), name="2fa-setup"),
    path("confirm/", TwoFAConfirmView.as_view(), name="2fa-confirm"),
    path("disable/", TwoFADisableView.as_view(), name="2fa-disable"),
    path("login/", TwoFALoginView.as_view(), name="2fa-login"),
]
"""Mounted by ``karni/accounts/urls.py`` under ``2fa/`` when ``KARNI_2FA`` is on.

Override / escape hatch: declare your own ``path("api/auth/2fa/<name>/", ...)``
before including ``karni.accounts.urls`` — first match wins.
"""
