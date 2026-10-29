"""Experimental. Sign in with a one-time code sent by email, in JWT and session mode.

The user types an address and gets a short numeric code by email. They type
the code back and are signed in, with no password:

1. ``POST <auth mount>/otp/send/ {"email"}`` calls :func:`send_code`. The
   answer is the same 200 for every address, whether it has an account, is
   inactive, or may not sign up.
2. ``POST <auth mount>/otp/verify/ {"email", "code"}`` calls
   :func:`verify_code`, and the view answers exactly like ``login/``: a token
   pair in JWT mode, a session in session mode, or the 2FA gate.

Both routes exist only while ``KARNI_EMAIL_OTP`` is true.

How a code is kept:

* The code comes from :mod:`secrets`, uniform over every string of
  ``KARNI_EMAIL_OTP_LENGTH`` digits (:func:`generate_code`).
* Only :func:`hash_code` is stored: an HMAC-SHA256 keyed by ``SECRET_KEY``
  over the lower-cased address and the code, in
  :class:`karni.accounts.models.LoginCode`. The code is never stored or
  logged, and :func:`code_matches` compares with :func:`hmac.compare_digest`.
* A code dies when it is used, when ``KARNI_EMAIL_OTP_TTL`` seconds pass, or
  when ``KARNI_EMAIL_OTP_MAX_ATTEMPTS`` guesses were made: a wrong guess that
  reaches the cap kills it, and the right code is refused after that.
  Sending a new code deletes the earlier ones for the address.

Who gets in follows ``KARNI_EMAIL_OTP_SIGNUP``, the same three policies as
sign-in with an ID token (:data:`karni.accounts.social_token.SIGNUP_POLICIES`).
A user is created only when a code is verified, never when one is sent.

Every refusal of a code is one :class:`LoginCodeRefused` with the code
``E235``, whatever the reason: wrong, expired, used, locked, or an address
nobody sent a code to. The reason goes only to the ``accounts.otp.refused``
log event. An inactive account answers ``E226`` after a right code, a new
account under the ``approval`` policy ``E224`` (202), and the routes answer
``E236`` (404) while the setting is off.

Override / escape hatch: call :func:`send_code` and :func:`verify_code` from
a view of your own (declare its path before ``include("karni.accounts.urls")``),
replace the email through the ``login_code`` templates or
``KARNI_ACCOUNTS_EMAIL_BACKEND``, and tune the throttle scopes
``auth.otp_send``, ``auth.otp_send_email`` and ``auth.otp_verify``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, cast

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from karni.errorcodes import KarniError

if TYPE_CHECKING:
    from karni.accounts.models import AbstractKarniUser

__all__ = [
    "DEFAULT_LENGTH",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_TTL",
    "EMAIL_TEMPLATE",
    "LENGTH_RANGE",
    "MAX_ATTEMPTS_RANGE",
    "TTL_RANGE",
    "CodeSignIn",
    "LoginCodeRefused",
    "code_length",
    "code_matches",
    "code_ttl",
    "enabled",
    "flush_expired_codes",
    "generate_code",
    "hash_code",
    "max_attempts",
    "normalize_address",
    "send_answer",
    "send_code",
    "signup_policy",
    "turned_off",
    "verify_code",
]

#: Experimental. Seconds a code lives unless ``KARNI_EMAIL_OTP_TTL`` says otherwise.
DEFAULT_TTL: Final = 600
#: Experimental. Digits in a code unless ``KARNI_EMAIL_OTP_LENGTH`` says otherwise.
DEFAULT_LENGTH: Final = 6
#: Experimental. Guesses a code takes unless ``KARNI_EMAIL_OTP_MAX_ATTEMPTS`` says otherwise.
DEFAULT_MAX_ATTEMPTS: Final = 5
#: Experimental. The lengths ``KARNI_EMAIL_OTP_LENGTH`` may take, inclusive.
LENGTH_RANGE: Final = (4, 10)
#: Experimental. The lifetimes ``KARNI_EMAIL_OTP_TTL`` may take, in seconds, inclusive.
TTL_RANGE: Final = (60, 3600)
#: Experimental. The caps ``KARNI_EMAIL_OTP_MAX_ATTEMPTS`` may take, inclusive.
MAX_ATTEMPTS_RANGE: Final = (1, 10)
#: Experimental. The accounts email template stem: ``karni_accounts/email/login_code_*``.
EMAIL_TEMPLATE: Final = "login_code"

#: Mixed into every HMAC so a code hash can never stand for another Karni value.
_HMAC_CONTEXT: Final = b"karni.accounts.login_code"
_LIFT_REASON: Final = "sign-in with a code: an address stays reserved by a deleted account"
_CLEANUP_REASON: Final = "sign-in with a code: dead codes go, deleted or not"
_GENERIC_DETAIL: Final = "The code is wrong or has expired. Ask for a new code."


# refusals


class LoginCodeRefused(KarniError):
    """Experimental. A refused sign-in by code, with its code and the HTTP answer.

    ``code`` is ``E235`` for every failure of the code itself (and for an
    address that may not sign up), ``E226`` for an inactive account, ``E224``
    (202) for a new account awaiting approval and ``E236`` (404) while the
    feature is off. ``reason`` is a short word for the ``accounts.otp.refused``
    log event only: the answer never carries it. ``email`` is the address, so
    the log can carry its fingerprint (never the address itself).
    """

    def __init__(
        self,
        reason: str,
        message: str = _GENERIC_DETAIL,
        *,
        code: str = "E235",
        status: int = 401,
        email: str | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.reason = reason
        self.status = status
        self.email = email

    def payload(self) -> dict[str, Any]:
        """The response body: ``{"code", "detail"}`` (plus ``awaiting_approval`` for E224)."""
        body: dict[str, Any] = {"code": self.code, "detail": str(self)}
        if self.code == "E224":
            body["awaiting_approval"] = True
        return body


def turned_off() -> LoginCodeRefused:
    """Experimental. The ``E236`` refusal the routes answer while ``KARNI_EMAIL_OTP`` is false."""
    return LoginCodeRefused(
        "turned_off",
        "Sign-in with a code is turned off: KARNI_EMAIL_OTP is False.",
        code="E236",
        status=404,
    )


# settings


def enabled() -> bool:
    """Experimental. Whether sign-in with a code is on (``KARNI_EMAIL_OTP``), read per request."""
    return bool(getattr(settings, "KARNI_EMAIL_OTP", False))


def code_ttl() -> int:
    """Experimental. Seconds a new code lives (``KARNI_EMAIL_OTP_TTL``, default 600)."""
    return int(getattr(settings, "KARNI_EMAIL_OTP_TTL", DEFAULT_TTL))


def code_length() -> int:
    """Experimental. Digits in a new code (``KARNI_EMAIL_OTP_LENGTH``, default 6)."""
    return int(getattr(settings, "KARNI_EMAIL_OTP_LENGTH", DEFAULT_LENGTH))


def max_attempts() -> int:
    """Experimental. Guesses a code takes before it dies (``KARNI_EMAIL_OTP_MAX_ATTEMPTS``)."""
    return int(getattr(settings, "KARNI_EMAIL_OTP_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS))


def signup_policy() -> str:
    """Experimental. ``KARNI_EMAIL_OTP_SIGNUP``: ``open``, ``approval`` or ``existing``.

    ``None`` follows ``KARNI_ACCOUNTS_REGISTRATION``, exactly as sign-in with
    an ID token does (:func:`karni.accounts.social_token.signup_policy`).
    """
    from karni.accounts.social_token import signup_policy as resolve

    return resolve("KARNI_EMAIL_OTP_SIGNUP")


def send_answer() -> dict[str, Any]:
    """Experimental. The body ``otp/send/`` answers on every path, whatever the address.

    ``length`` and ``expires_in`` come from the settings, never from the
    address, so a client can size its code input without learning anything.
    """
    return {
        "detail": "If this address may sign in, a sign-in code is on its way to it.",
        "length": code_length(),
        "expires_in": code_ttl(),
    }


# the code


def normalize_address(email: str) -> str:
    """Experimental. The form an address is stored, hashed and throttled in: trimmed, lower case."""
    return email.strip().lower()


def generate_code(length: int | None = None) -> str:
    """Experimental. A new code: ``length`` digits, uniform, from :mod:`secrets`.

    Leading zeros are kept, so every one of the ``10 ** length`` strings is
    equally likely.
    """
    digits = code_length() if length is None else length
    return f"{secrets.randbelow(10**digits):0{digits}d}"


def hash_code(address: str, code: str) -> str:
    """Experimental. HMAC-SHA256, keyed by ``SECRET_KEY``, over the address and the code.

    The only form a code is stored in. ``address`` is
    :func:`normalize_address`'s. Binding the address in means a hash says
    nothing about the same code sent to someone else, and a stolen table is
    useless without ``SECRET_KEY``.
    """
    message = b"\x00".join(
        (_HMAC_CONTEXT, normalize_address(address).encode(), code.encode("utf-8"))
    )
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def code_matches(stored_hash: str, address: str, code: str) -> bool:
    """Experimental. Whether ``code`` is the one ``stored_hash`` was made from, in constant time."""
    return hmac.compare_digest(stored_hash, hash_code(address, code))


# sending


def _user_model() -> type[AbstractKarniUser]:
    return cast("type[AbstractKarniUser]", get_user_model())


def _account(address: str) -> AbstractKarniUser | None:
    """The account holding ``address``, deleted ones included (their address stays taken)."""
    return cast(
        "AbstractKarniUser | None",
        _user_model()
        .objects.without("soft_delete", reason=_LIFT_REASON)
        .filter(email__iexact=address)
        .first(),
    )


def _log() -> Any:
    import structlog

    return structlog.get_logger("karni.accounts")


def _fingerprint(email: str) -> str:
    from karni.accounts.api.views import email_fingerprint

    return email_fingerprint(email)


def _deliver(to: str, code: str, user: AbstractKarniUser | None, ttl: int) -> None:
    """Send the ``login_code`` email. A failure is logged, never raised.

    The answer to ``otp/send/`` must not change with the address, so a mail
    server that refuses one cannot turn into a 500 for that address only.
    """
    from karni.accounts.emails import AccountsEmail, get_email_backend

    context = {"code": code, "ttl_minutes": max(1, ttl // 60), "user": user}
    try:
        get_email_backend().send(AccountsEmail(template=EMAIL_TEMPLATE, to=to, context=context))
    except Exception as exc:  # noqa: BLE001 - the answer must not depend on delivery
        _log().error("accounts.otp.email_failed", email=_fingerprint(to), error=type(exc).__name__)


def send_code(email: str) -> bool:
    """Experimental. Store a new code for ``email`` and email it when the address may sign in.

    Every address gets the same work: the account lookup, a new code, its
    HMAC, the cleanup and one stored row (``user`` is ``None`` without an
    account). The email goes out after the transaction commits, through the
    configured accounts email backend, to an address whose account is not
    deleted (active or not), or that the sign-up policy lets in (``open`` and
    ``approval``). Any other address gets a row nobody has the code for, and
    no email, so ``verify/`` behaves the same for it.

    Sending deletes every earlier code for the address and every expired
    code, so one code per address is alive. No user is ever created here.

    Returns whether an email was queued. The view never tells the caller.
    """
    from karni.accounts.models import LoginCode

    address = normalize_address(email)
    code = generate_code()
    digest = hash_code(address, code)
    account = _account(address)
    policy = signup_policy()
    if account is None:
        mailed, reason = policy in ("open", "approval"), "signup_closed"
    else:
        mailed, reason = account.deleted_at is None, "deleted"
    now = timezone.now()
    ttl = code_ttl()
    recipient = (
        account.email
        if account is not None
        else _user_model().objects.normalize_email(email.strip())
    )
    with transaction.atomic():
        LoginCode.objects.without("soft_delete", reason=_CLEANUP_REASON).filter(
            Q(email=address) | Q(expires_at__lte=now)
        ).hard_delete()
        LoginCode.objects.create(
            email=address,
            user=account,
            code_hash=digest,
            expires_at=now + timedelta(seconds=ttl),
        )
        if mailed:
            transaction.on_commit(lambda: _deliver(recipient, code, account, ttl))
    if mailed:
        _log().info(
            "accounts.otp.sent",
            email=_fingerprint(address),
            **({"user_id": str(account.pk)} if account is not None else {"new_address": True}),
        )
    else:
        _log().info("accounts.otp.refused", step="send", reason=reason, email=_fingerprint(address))
    return mailed


# verifying


@dataclass(frozen=True)
class CodeSignIn:
    """Experimental. What :func:`verify_code` decided.

    ``user`` signs in unless ``awaiting_approval`` (a new, inactive account
    under the ``approval`` policy). ``created`` says whether this sign-in
    created the account.
    """

    user: AbstractKarniUser
    created: bool = False
    awaiting_approval: bool = False


def _refused(reason: str, address: str) -> LoginCodeRefused:
    return LoginCodeRefused(reason, email=address)


def _consume(address: str, code: str) -> None:
    """Spend one guess on the address's live code. Return only when ``code`` is right.

    Each guess first takes one attempt with a filtered ``UPDATE``, so parallel
    guesses can never exceed the cap. Only then is the code compared, and a
    right one is claimed with a second filtered ``UPDATE`` (a replay loses).
    """
    from karni.accounts.models import LoginCode

    digest = hash_code(address, code)
    now = timezone.now()
    row = LoginCode.objects.filter(email=address).order_by("-created_at").first()
    if row is None:
        raise _refused("no_code", address)
    if row.used_at is not None:
        raise _refused("used", address)
    if row.expires_at <= now:
        raise _refused("expired", address)
    cap = max_attempts()
    if row.attempts >= cap:
        raise _refused("locked", address)
    took = LoginCode.objects.filter(
        pk=row.pk, used_at__isnull=True, attempts__lt=cap, expires_at__gt=now
    ).update(attempts=F("attempts") + 1)
    if not took:
        raise _refused("locked", address)
    if not hmac.compare_digest(row.code_hash, digest):
        spent = LoginCode.objects.filter(pk=row.pk).values_list("attempts", flat=True).first()
        if spent is not None and spent >= cap:
            _log().warning("accounts.otp.locked", email=_fingerprint(address), attempts=spent)
        raise _refused("wrong_code", address)
    claimed = LoginCode.objects.filter(pk=row.pk, used_at__isnull=True).update(used_at=now)
    if not claimed:
        raise _refused("used", address)


def _create(email: str, *, active: bool) -> AbstractKarniUser:
    """Create the account the code just proved the address of: verified, no password."""
    from karni.accounts.permissions import assign_role

    with transaction.atomic():
        user = _user_model().objects.create_user(
            email=email, password=None, email_verified=True, is_active=active
        )
        for role in getattr(settings, "KARNI_ACCOUNTS_DEFAULT_ROLES", None) or ():
            assign_role(user, role)
    _log().info("accounts.otp.created", user_id=str(user.pk), active=active)
    return user


def _sign_in(account: AbstractKarniUser, address: str) -> CodeSignIn:
    from karni.accounts.services import prove_address

    if account.deleted_at is not None:
        raise _refused("deleted", address)
    if not account.is_active:
        raise LoginCodeRefused("inactive", "This account is inactive.", code="E226", email=address)
    prove_address(account)
    return CodeSignIn(user=account)


def verify_code(email: str, code: str) -> CodeSignIn:
    """Experimental. Spend ``code`` on ``email`` and return the account it signs in.

    Whitespace inside the code is ignored (``"123 456"``). Any failure of the
    code is the same :class:`LoginCodeRefused` (``E235``), with the precise
    reason only in ``.reason``. A right code then:

    1. signs in the account that holds the address now, if it is active, and
       marks the address verified (:func:`karni.accounts.services.prove_address`:
       an account never verified also loses its password). An inactive
       account is refused with ``E226``, a deleted one with ``E235`` (it is
       sent no code, so nobody can know one).
    2. otherwise follows ``KARNI_EMAIL_OTP_SIGNUP``: ``open`` creates an
       active, verified account with no password and the
       ``KARNI_ACCOUNTS_DEFAULT_ROLES``, ``approval`` creates it inactive
       (``awaiting_approval``), and ``existing`` refuses with ``E235``.

    Override / escape hatch: call it from your own view, or replace the view.
    """
    address = normalize_address(email)
    _consume(address, "".join(code.split()))
    account = _account(address)
    if account is not None:
        return _sign_in(account, address)
    policy = signup_policy()
    if policy == "existing":
        raise _refused("signup_closed", address)
    try:
        user = _create(
            _user_model().objects.normalize_email(email.strip()), active=policy != "approval"
        )
    except IntegrityError:
        # Another request opened the account in between: the code proved its address.
        account = _account(address)
        if account is None:  # pragma: no cover - the integrity error came from elsewhere
            raise
        return _sign_in(account, address)
    return CodeSignIn(user=user, created=True, awaiting_approval=policy == "approval")


# cleanup


def flush_expired_codes() -> int:
    """Experimental. Delete every code past its expiry. Returns how many rows went.

    ``karni.accounts.tasks.flush_login_codes`` runs it every hour while
    ``KARNI_EMAIL_OTP`` is on, and :func:`send_code` does the same on each send.
    """
    from karni.accounts.models import LoginCode

    expired = LoginCode.objects.without("soft_delete", reason=_CLEANUP_REASON).filter(
        expires_at__lte=timezone.now()
    )
    deleted, _per_model = expired.hard_delete()
    return int(deleted)
