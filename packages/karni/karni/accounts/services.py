"""Account flows for :mod:`karni.accounts` — all business logic lives here.

Views and serializers stay thin: they validate transport-level input and call
these module-level functions. Consume-side flows (:func:`verify_email`,
:func:`confirm_password_reset`, :func:`confirm_email_change`) wrap token
consumption and the user mutation in a single ``transaction.atomic()`` block,
so a failure (weak password, uniqueness race) rolls the token back to unused
and the emailed link keeps working.

Error contract:

* Token problems raise :class:`karni.accounts.tokens.TokenError` with a
  ``reason`` of ``"invalid"``, ``"expired"`` or ``"used"`` — views map these
  to HTTP 400.
* Input problems (weak password, duplicate email) raise DRF's
  :class:`rest_framework.exceptions.ValidationError`, which DRF's default
  exception handler already renders as HTTP 400 — no per-view handling
  required.

Override / escape hatch: these are deliberately plain functions, not a
swappable service class. To change a flow, subclass the serializer or view
that calls it and call your own function instead (first match wins when your
URL pattern is declared before ``include("karni.accounts.urls")``). Email
delivery and link targets are overridable on their own via
``KARNI_ACCOUNTS_EMAIL_BACKEND`` / ``KARNI_ACCOUNTS_LINKS`` — see
:mod:`karni.accounts.emails`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from karni.accounts.emails import AccountsEmail, build_link, get_email_backend
from karni.accounts.permissions import assign_role
from karni.accounts.tokens import TokenError, consume_token, issue_token

if TYPE_CHECKING:
    from karni.accounts.models import AbstractKarniUser

__all__ = [
    "blacklist_user_refresh_tokens",
    "confirm_email_change",
    "confirm_password_reset",
    "register",
    "request_email_change",
    "request_password_reset",
    "send_verification",
    "verify_email",
]

_TOKEN_BLACKLIST_APP = "rest_framework_simplejwt.token_blacklist"


def _user_model() -> type[AbstractKarniUser]:
    """Return the active user model, typed as :class:`AbstractKarniUser`."""
    return cast("type[AbstractKarniUser]", get_user_model())


def _send_account_email(
    template: str,
    to: str,
    user: AbstractKarniUser,
    secret: str,
    **extra: Any,
) -> None:
    """Send one account email through the configured backend.

    The context always carries ``user``, ``token`` (the raw secret) and
    ``link`` (built by :func:`karni.accounts.emails.build_link`); ``extra``
    keys are merged in for flow-specific data such as ``new_email``.
    """
    context: dict[str, Any] = {
        "user": user,
        "token": secret,
        "link": build_link(template, secret),
        **extra,
    }
    get_email_backend().send(AccountsEmail(template=template, to=to, context=context))


def _validate_password(password: str, user: AbstractKarniUser) -> None:
    """Run Django's ``AUTH_PASSWORD_VALIDATORS``, re-raising as DRF 400 input.

    Override / escape hatch: tune the validators themselves via the standard
    ``AUTH_PASSWORD_VALIDATORS`` setting.
    """
    try:
        password_validation.validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError({"new_password": exc.messages}) from exc


def blacklist_user_refresh_tokens(user: AbstractKarniUser) -> int:
    """Blacklist every outstanding SimpleJWT refresh token for ``user``.

    Called after a password reset or password change so stolen refresh tokens
    die with the old credential; access tokens stay valid up to their short
    lifetime (15 minutes by default) — by design. A no-op returning ``0``
    when ``rest_framework_simplejwt.token_blacklist`` is not installed
    (e.g. pure session deployments that trimmed ``INSTALLED_APPS``).

    Returns the number of tokens newly blacklisted.

    Override / escape hatch: call this from any custom credential-rotation
    flow of your own; it is idempotent (``get_or_create`` per token).
    """
    if not apps.is_installed(_TOKEN_BLACKLIST_APP):
        return 0
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    blacklisted = 0
    for outstanding in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=outstanding)
        blacklisted += int(created)
    return blacklisted


def register(email: str, password: str, **fields: Any) -> AbstractKarniUser:
    """Create a user and queue their verification email.

    The user is created via the model manager's ``create_user`` (which
    normalizes and requires ``email``). The verification email is sent via
    ``transaction.on_commit`` so it never announces a registration that a
    surrounding transaction later rolls back; in eager test transactions use
    ``django_capture_on_commit_callbacks`` to observe it.

    ``KARNI_ACCOUNTS_DEFAULT_ROLES`` (e.g. ``["attendee"]``) are assigned
    before the commit, so ``HasRole`` works from the first request.

    Uniqueness is enforced by the serializer at the API layer (a duplicate
    email is a 400 there — documented, accepted enumeration surface); calling
    this function directly with a duplicate email raises ``IntegrityError``.
    """
    user = _user_model().objects.create_user(email=email, password=password, **fields)
    for role in getattr(settings, "KARNI_ACCOUNTS_DEFAULT_ROLES", None) or ():
        assign_role(user, role)
    transaction.on_commit(lambda: send_verification(user))
    return user


def send_verification(user: AbstractKarniUser) -> None:
    """Issue a fresh ``verify_email`` token and email its link to ``user``.

    Reissuing invalidates any earlier unused verification token (single
    active token per purpose), so only the newest emailed link works.
    """
    secret = issue_token(user, "verify_email")
    _send_account_email("verify_email", user.email, user, secret)


def verify_email(secret: str) -> AbstractKarniUser:
    """Consume a ``verify_email`` token and mark the owner's email verified.

    Replay-safe: the token is consumed atomically with the flag update, and a
    second call with the same secret raises ``TokenError("used")``.

    :raises karni.accounts.tokens.TokenError: unknown, expired or used token.
    """
    with transaction.atomic():
        token = consume_token(secret, "verify_email")
        user = cast("AbstractKarniUser", token.user)
        if not user.email_verified:
            user.email_verified = True
            user.save(update_fields=["email_verified", "updated_at"])
    return user


def request_password_reset(email: str) -> None:
    """Email a password-reset link if an active account matches ``email``.

    Deliberately silent when no active user matches — the reset endpoint must
    not reveal whether an address is registered (no user enumeration), so this
    function returns ``None`` either way and callers respond identically.
    """
    user_model = _user_model()
    normalized = user_model.objects.normalize_email(email)
    user = cast(
        "AbstractKarniUser | None",
        user_model.objects.filter(email__iexact=normalized, is_active=True).first(),
    )
    if user is None:
        return
    secret = issue_token(user, "reset_password")
    _send_account_email("reset_password", user.email, user, secret)


def confirm_password_reset(secret: str, new_password: str) -> AbstractKarniUser:
    """Consume a ``reset_password`` token and set ``new_password``.

    Runs Django's password validators against the token's owner; a rejected
    password rolls the whole transaction back, so the token stays unused and
    the emailed link can be retried with a stronger password. On success all
    outstanding refresh tokens are blacklisted
    (:func:`blacklist_user_refresh_tokens`) so old sessions can't outlive the
    reset.

    :raises karni.accounts.tokens.TokenError: unknown, expired or used token.
    :raises rest_framework.exceptions.ValidationError: password rejected by
        ``AUTH_PASSWORD_VALIDATORS``.
    """
    with transaction.atomic():
        token = consume_token(secret, "reset_password")
        user = cast("AbstractKarniUser", token.user)
        _validate_password(new_password, user)
        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])
        blacklist_user_refresh_tokens(user)
    return user


def request_email_change(user: AbstractKarniUser, new_email: str) -> None:
    """Start an email change: validate uniqueness, email the NEW address.

    The confirmation link is sent to ``new_email`` — clicking it is what
    proves the user controls the new mailbox. A duplicate address is rejected
    here with a DRF ``ValidationError`` (400); uniqueness is re-checked at
    confirm time because another account may claim the address in between.
    """
    user_model = _user_model()
    normalized = user_model.objects.normalize_email(new_email)
    taken = user_model.objects.filter(email__iexact=normalized).exclude(pk=user.pk).exists()
    if taken:
        raise ValidationError({"new_email": ["A user with this email address already exists."]})
    secret = issue_token(user, "change_email", new_email=normalized)
    _send_account_email("change_email", normalized, user, secret, new_email=normalized)


def confirm_email_change(secret: str) -> AbstractKarniUser:
    """Consume a ``change_email`` token and move the account to its new email.

    Uniqueness is re-checked inside the transaction, and a database-level
    uniqueness race (another account grabbing the address between the check
    and the write) surfaces as ``TokenError("invalid")`` rather than a 500.
    ``email_verified`` is set ``True``: following the emailed link proves the
    user owns the new address.

    :raises karni.accounts.tokens.TokenError: unknown, expired or used token,
        a token issued without a target address, or a now-taken address.
    """
    user_model = _user_model()
    try:
        with transaction.atomic():
            token = consume_token(secret, "change_email")
            user = cast("AbstractKarniUser", token.user)
            new_email = token.new_email
            if not new_email:
                raise TokenError("invalid")
            taken = user_model.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists()
            if taken:
                raise TokenError("invalid")
            user.email = new_email
            user.email_verified = True
            user.save(update_fields=["email", "email_verified", "updated_at"])
    except IntegrityError as exc:
        raise TokenError("invalid") from exc
    return user
