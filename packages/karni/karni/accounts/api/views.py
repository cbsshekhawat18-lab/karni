"""Thin DRF views for the :mod:`karni.accounts` auth endpoints.

Every view reads ``settings.KARNI_AUTH_MODE`` **at request time** (amendment
A3): the URLconf is identical in ``jwt`` and ``session`` mode, the behaviour
branches per request, and ``override_settings(KARNI_AUTH_MODE=...)`` is fully
testable. Business logic lives in :mod:`karni.accounts.services`; these views
only validate transport input, call a service and map
:class:`karni.accounts.tokens.TokenError` onto HTTP 400 (the services raise
DRF ``ValidationError`` for input problems themselves).

Security posture baked in here:

* per-IP scoped throttles plus the per-account login throttle (amendment A5),
* CSRF bootstrap for SPAs: ``ensure_csrf_cookie`` on login and the dedicated
  ``csrf/`` endpoint (amendment A4),
* a password change blacklists every outstanding refresh token while session
  mode keeps the changer's own session alive (amendment A1),
* the 2FA login gate withholds credentials until ``2fa/login/`` verifies a
  TOTP code (contract §2FA; ``karni.accounts.twofa`` is imported lazily so
  core installs never touch ``django-otp``).

Override / escape hatch: subclass any view and declare its URL before
``include("karni.accounts.urls")`` (first match wins, amendment A11); every
DRF hook (``permission_classes``, ``throttle_classes``, ``serializer_class``,
...) is an ordinary class attribute.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import update_last_login
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import generics, status
from rest_framework.exceptions import AuthenticationFailed, MethodNotAllowed, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError as JWTTokenError
from rest_framework_simplejwt.settings import api_settings as simplejwt_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from karni.accounts import services
from karni.accounts.api.serializers import (
    EmailChangeSerializer,
    LoginSerializer,
    LogoutSerializer,
    MeSerializer,
    OneTimeTokenSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    RegisterSerializer,
)
from karni.accounts.api.throttles import AccountRateThrottle, AuthScopedRateThrottle
from karni.accounts.tokens import TokenError

__all__ = [
    "MODE_JWT",
    "MODE_SESSION",
    "CsrfView",
    "EmailChangeConfirmView",
    "EmailChangeView",
    "EmailVerifyResendView",
    "EmailVerifyView",
    "LoginView",
    "LogoutView",
    "MeView",
    "PasswordChangeView",
    "PasswordResetConfirmView",
    "PasswordResetView",
    "RefreshView",
    "RegisterView",
    "auth_mode",
]

MODE_JWT = "jwt"
MODE_SESSION = "session"


def auth_mode() -> str:
    """The active auth mode, read per request (amendment A3).

    ``"jwt"`` (the default) or ``"session"``; validated by
    :mod:`karni.conf.validation` at startup, so anything else never gets here
    in a running project.
    """
    return str(getattr(settings, "KARNI_AUTH_MODE", MODE_JWT))


_TOKEN_ERROR_MESSAGES: dict[str, str] = {
    "invalid": "This token is invalid.",
    "expired": "This token has expired.",
    "used": "This token has already been used.",
}


def _token_validation_error(exc: TokenError) -> ValidationError:
    """Map a service-layer :class:`TokenError` onto a DRF 400 on ``token``.

    Only the reason category is disclosed — never whether an account exists
    or which user a token belonged to.
    """
    reason = getattr(exc, "reason", "invalid")
    message = _TOKEN_ERROR_MESSAGES.get(reason, _TOKEN_ERROR_MESSAGES["invalid"])
    return ValidationError({"token": [message]})


def _issue_jwt_pair(user: AbstractBaseUser) -> dict[str, str]:
    """Mint a SimpleJWT refresh/access pair for ``user``.

    Honours SimpleJWT's ``UPDATE_LAST_LOGIN`` setting; session-mode logins get
    ``last_login`` for free via Django's ``user_logged_in`` signal instead.
    """
    refresh = RefreshToken.for_user(user)
    if simplejwt_settings.UPDATE_LAST_LOGIN:
        update_last_login(None, user)  # type: ignore[arg-type]
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _session_login(request: Request, user: AbstractBaseUser) -> None:
    """Open a Django session for ``user`` on this request.

    ``authenticate()`` stamps ``user.backend`` during a normal login; a user
    that arrived by another path (``KARNI_ACCOUNTS_AUTO_LOGIN`` after
    registration) is attributed to the first configured authentication
    backend. Django rotates the CSRF token here — the response still carries
    a valid cookie thanks to ``ensure_csrf_cookie`` (amendment A4).
    """
    backend = getattr(user, "backend", None) or settings.AUTHENTICATION_BACKENDS[0]
    auth_login(request, user, backend=backend)


def _twofa_gate_payload(user: AbstractBaseUser) -> dict[str, Any] | None:
    """The 2FA login-gate payload, or ``None`` when login may proceed.

    Active only when ``KARNI_2FA`` is enabled *and* the user has a confirmed
    TOTP device: the response then carries ``requires_2fa`` plus a short-lived
    single-use ephemeral token (amendment A6) instead of credentials, and the
    client finishes at ``2fa/login/``. :mod:`karni.accounts.twofa` is imported
    lazily so installations without the ``karni[2fa]`` extra never import it.
    """
    if not getattr(settings, "KARNI_2FA", False):
        return None
    from karni.accounts import twofa

    if not twofa.user_has_2fa(user):
        return None
    return {"requires_2fa": True, "ephemeral_token": twofa.issue_ephemeral_token(user)}


class RegisterView(APIView):
    """``POST register/`` — create an account, 201 with the profile payload.

    The response body is the :class:`MeSerializer` payload of the new user.
    With ``KARNI_ACCOUNTS_AUTO_LOGIN = True`` (default ``False``) the response
    additionally carries ``access``/``refresh`` in JWT mode, or opens a
    session in session mode. The verification email goes out on transaction
    commit (amendment A7) through the configured accounts email backend.
    """

    permission_classes: ClassVar[list[type]] = [AllowAny]
    throttle_classes: ClassVar[list[type]] = [AuthScopedRateThrottle]
    throttle_scope = "auth.register"
    serializer_class = RegisterSerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        email = fields.pop("email")
        password = fields.pop("password")
        user = services.register(email, password, **fields)

        data: dict[str, Any] = dict(MeSerializer(user, context={"request": request}).data)
        if getattr(settings, "KARNI_ACCOUNTS_AUTO_LOGIN", False):
            if auth_mode() == MODE_JWT:
                data.update(_issue_jwt_pair(user))
            else:
                _session_login(request, user)
        return Response(data, status=status.HTTP_201_CREATED)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class LoginView(APIView):
    """``POST login/`` — authenticate with email and password (both modes).

    JWT mode → ``{"access", "refresh", "user"}``; session mode → Django
    session plus ``{"user"}``. When the account has confirmed 2FA the
    response is the gate payload (``requires_2fa`` + ``ephemeral_token``) and
    *no* credentials — see :func:`_twofa_gate_payload`. ``ensure_csrf_cookie``
    guarantees SPAs a CSRF cookie from the very first auth call (amendment
    A4); the per-account throttle rides alongside the per-IP one (A5).
    """

    permission_classes: ClassVar[list[type]] = [AllowAny]
    throttle_classes: ClassVar[list[type]] = [AuthScopedRateThrottle, AccountRateThrottle]
    throttle_scope = "auth.login"
    serializer_class = LoginSerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.user
        if user is None:  # pragma: no cover - TokenObtainSerializer raises first
            raise AuthenticationFailed()

        gate = _twofa_gate_payload(user)
        if gate is not None:
            return Response(gate)

        data: dict[str, Any] = {}
        if auth_mode() == MODE_JWT:
            data.update(_issue_jwt_pair(user))
        else:
            _session_login(request, user)
        data["user"] = MeSerializer(user, context={"request": request}).data
        return Response(data)


class LogoutView(APIView):
    """``POST logout/`` — end the current credential.

    JWT mode blacklists the posted refresh token (the short-lived access
    token expires on its own — by design, amendment A1's documented window);
    session mode flushes the Django session. 204 on success.
    """

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]
    serializer_class = LogoutSerializer

    def post(self, request: Request) -> Response:
        if auth_mode() == MODE_JWT:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            refresh = serializer.validated_data["refresh"]
            if not refresh:
                raise ValidationError({"refresh": ["This field is required in JWT auth mode."]})
            try:
                token = RefreshToken(refresh)
            except JWTTokenError as exc:
                raise ValidationError({"refresh": [str(exc)]}) from exc
            # ``blacklist`` exists whenever the token_blacklist app is
            # installed — unconditional in Karni's conf (amendment A3); the
            # guard keeps logout working for projects that trimmed it out.
            if hasattr(token, "blacklist"):
                token.blacklist()
        else:
            auth_logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RefreshView(TokenRefreshView):
    """``POST refresh/`` — rotate a refresh token (JWT mode only).

    Session mode answers 405 from the view (amendment A3 — the URL exists in
    both modes): the session cookie is the credential there and renews
    itself. JWT mode delegates to SimpleJWT's ``TokenRefreshView``; with
    Karni's conf defaults refresh tokens rotate and the old one is
    blacklisted (``ROTATE_REFRESH_TOKENS`` / ``BLACKLIST_AFTER_ROTATION``).
    """

    throttle_classes: ClassVar[list[type]] = [AuthScopedRateThrottle]
    throttle_scope = "auth.token"

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if auth_mode() != MODE_JWT:
            raise MethodNotAllowed(
                request.method or "POST",
                detail=(
                    "Token refresh is disabled in session auth mode "
                    '(KARNI_AUTH_MODE="session"); the session cookie is the '
                    "credential and needs no refresh."
                ),
            )
        return super().post(request, *args, **kwargs)


class MeView(generics.RetrieveUpdateAPIView):
    """``GET``/``PATCH me/`` — the authenticated user's profile.

    PATCH accepts only the safe fields (``first_name`` / ``last_name``);
    everything else in :class:`MeSerializer` is read-only, and read-only
    fields in a payload are ignored, not errors. PUT is deliberately absent —
    the profile is never wholly replaced through this endpoint.
    """

    serializer_class = MeSerializer
    permission_classes: ClassVar[list[type]] = [IsAuthenticated]
    http_method_names: ClassVar[list[str]] = ["get", "patch", "head", "options"]

    def get_object(self) -> AbstractBaseUser:
        return self.request.user


class PasswordChangeView(APIView):
    """``POST password/change/`` — rotate the password (auth required).

    Requires the current password. On success every outstanding refresh token
    is blacklisted (amendment A1 — stolen refresh tokens die with the old
    credential; access tokens live out their short lifetime by design), and in
    session mode ``update_session_auth_hash`` keeps the changer's own session
    alive while every other session's auth hash goes stale.
    """

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]
    serializer_class = PasswordChangeSerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        services.blacklist_user_refresh_tokens(user)
        if auth_mode() == MODE_SESSION:
            update_session_auth_hash(request, user)
        return Response({"detail": "Password changed."})


class PasswordResetView(APIView):
    """``POST password/reset/`` — request a reset link, enumeration-silent.

    Always 200 with the same body whether or not the address has an account
    (amendment A9): the only reset endpoint that must never reveal existence.
    """

    permission_classes: ClassVar[list[type]] = [AllowAny]
    throttle_classes: ClassVar[list[type]] = [AuthScopedRateThrottle]
    throttle_scope = "auth.password_reset"
    serializer_class = PasswordResetSerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(serializer.validated_data["email"])
        detail = "If an account exists for this address, a password reset link has been sent."
        return Response({"detail": detail})


class PasswordResetConfirmView(APIView):
    """``POST password/reset/confirm/`` — set a new password via the link.

    Token consumption, password validation and the amendment-A1 refresh-token
    blacklisting all happen atomically in
    :func:`karni.accounts.services.confirm_password_reset`; a rejected
    password rolls back and leaves the token usable (amendment A7).
    """

    permission_classes: ClassVar[list[type]] = [AllowAny]
    throttle_classes: ClassVar[list[type]] = [AuthScopedRateThrottle]
    throttle_scope = "auth.password_reset"
    serializer_class = PasswordResetConfirmSerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.confirm_password_reset(
                serializer.validated_data["token"],
                serializer.validated_data["new_password"],
            )
        except TokenError as exc:
            raise _token_validation_error(exc) from exc
        return Response({"detail": "Password has been reset."})


class EmailVerifyView(APIView):
    """``POST email/verify/`` ``{token}`` — confirm ownership of the address."""

    permission_classes: ClassVar[list[type]] = [AllowAny]
    throttle_classes: ClassVar[list[type]] = [AuthScopedRateThrottle]
    throttle_scope = "auth.verify"
    serializer_class = OneTimeTokenSerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.verify_email(serializer.validated_data["token"])
        except TokenError as exc:
            raise _token_validation_error(exc) from exc
        return Response({"detail": "Email address verified."})


class EmailVerifyResendView(APIView):
    """``POST email/verify/resend/`` — email a fresh verification link.

    Auth required, so it may answer honestly (amendment A9): an
    already-verified account gets a 200 saying so instead of pointless mail.
    Reissuing invalidates the previously emailed link (single active token
    per purpose).
    """

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]
    throttle_classes: ClassVar[list[type]] = [AuthScopedRateThrottle]
    throttle_scope = "auth.verify"

    def post(self, request: Request) -> Response:
        user = request.user
        if getattr(user, "email_verified", False):
            return Response({"detail": "Email address is already verified."})
        services.send_verification(user)
        return Response({"detail": "Verification email sent."}, status=status.HTTP_202_ACCEPTED)


class EmailChangeView(APIView):
    """``POST email/change/`` ``{new_email, current_password}`` — start the flow.

    Auth plus the current password; the confirmation link is emailed to the
    *new* address (clicking it proves ownership). A taken address is a 400
    here and re-checked at confirm time (services layer, amendments A7/A9).
    """

    permission_classes: ClassVar[list[type]] = [IsAuthenticated]
    throttle_classes: ClassVar[list[type]] = [AuthScopedRateThrottle]
    throttle_scope = "auth.email_change"
    serializer_class = EmailChangeSerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        services.request_email_change(request.user, serializer.validated_data["new_email"])
        return Response(
            {"detail": "A confirmation link has been sent to the new address."},
            status=status.HTTP_202_ACCEPTED,
        )


class EmailChangeConfirmView(APIView):
    """``POST email/change/confirm/`` ``{token}`` — finish the email change.

    Anonymous on purpose: the emailed link lands on a frontend page without a
    session. A uniqueness race between request and confirm surfaces as a 400
    (``TokenError("invalid")``), never a 500 (amendment A7).
    """

    permission_classes: ClassVar[list[type]] = [AllowAny]
    throttle_classes: ClassVar[list[type]] = [AuthScopedRateThrottle]
    throttle_scope = "auth.email_change"
    serializer_class = OneTimeTokenSerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.confirm_email_change(serializer.validated_data["token"])
        except TokenError as exc:
            raise _token_validation_error(exc) from exc
        return Response({"detail": "Email address updated."})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """``GET csrf/`` — CSRF cookie bootstrap for SPAs (amendment A4).

    Returns 204 with the CSRF cookie set; a session-mode SPA calls this once
    before its first credentialed POST and sends the cookie's value back in
    the ``X-CSRFToken`` header. Harmless (and unnecessary) in JWT mode.
    """

    permission_classes: ClassVar[list[type]] = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response(status=status.HTTP_204_NO_CONTENT)
