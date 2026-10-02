"""Issue and consume the one-time tokens behind Karni's account flows.

Secrets never touch the database: :func:`issue_token` returns the plaintext
secret exactly once (to be embedded in an emailed link) and stores only its
SHA-256 digest. :func:`consume_token` is replay-safe under concurrency — the
used-at stamp is claimed with a filtered ``UPDATE`` whose row count decides
the winner.

Override / escape hatch: per-purpose lifetimes come from the
``KARNI_ACCOUNTS_TOKEN_TTL`` setting (a partial dict merged over
:data:`DEFAULT_TOKEN_TTL`); higher-level behaviour is overridden at the
service layer (:mod:`karni.accounts.services`), not here.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from karni.accounts.models import OneTimeToken

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

__all__ = [
    "DEFAULT_TOKEN_TTL",
    "TokenError",
    "consume_token",
    "hash_secret",
    "issue_token",
    "token_ttl",
]

DEFAULT_TOKEN_TTL: Final[dict[str, int]] = {
    OneTimeToken.Purpose.VERIFY_EMAIL.value: 86400,
    OneTimeToken.Purpose.RESET_PASSWORD.value: 3600,
    OneTimeToken.Purpose.CHANGE_EMAIL.value: 86400,
}
"""Per-purpose token lifetime in seconds; overridden (per key) by the
``KARNI_ACCOUNTS_TOKEN_TTL`` setting."""


class TokenError(Exception):
    """A one-time token could not be consumed.

    ``reason`` is one of ``"invalid"`` (no such token for the purpose),
    ``"expired"`` (past its ``expires_at``) or ``"used"`` (already consumed,
    superseded by a reissue, or lost a concurrent-consume race). Views map
    the reason onto their error payloads; nothing else is disclosed.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"One-time token is {reason}.")


def hash_secret(secret: str) -> str:
    """SHA-256 hex digest of a token secret — the only form ever stored."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def token_ttl(purpose: str) -> int:
    """Lifetime in seconds for ``purpose``.

    Reads the ``KARNI_ACCOUNTS_TOKEN_TTL`` setting and falls back to
    :data:`DEFAULT_TOKEN_TTL` per key, so projects may override a single
    purpose without restating the rest.
    """
    _require_known_purpose(purpose)
    configured: dict[str, int] = getattr(settings, "KARNI_ACCOUNTS_TOKEN_TTL", {})
    merged = {**DEFAULT_TOKEN_TTL, **configured}
    return int(merged[purpose])


def issue_token(
    user: AbstractBaseUser,
    purpose: str,
    *,
    new_email: str | None = None,
) -> str:
    """Create a one-time token for ``(user, purpose)`` and return its secret.

    The secret is ``secrets.token_urlsafe(32)``; only its hash is stored.
    Issuing invalidates any prior unused tokens for the same user and
    purpose (their ``used_at`` is stamped), so exactly one token per purpose
    is active at a time. ``new_email`` records the requested address for the
    ``change_email`` flow.

    :raises ValueError: when ``purpose`` is not a known
        :class:`~karni.accounts.models.OneTimeToken.Purpose` value.
    """
    _require_known_purpose(purpose)
    secret = secrets.token_urlsafe(32)
    now = timezone.now()
    with transaction.atomic():
        OneTimeToken.objects.filter(
            user=user,
            purpose=purpose,
            used_at__isnull=True,
        ).update(used_at=now)
        OneTimeToken.objects.create(
            user=user,
            purpose=purpose,
            token_hash=hash_secret(secret),
            new_email=new_email,
            expires_at=now + timedelta(seconds=token_ttl(purpose)),
        )
    return secret


def consume_token(secret: str, purpose: str) -> OneTimeToken:
    """Atomically consume the token identified by ``secret`` and ``purpose``.

    On success the token's ``used_at`` is claimed with a single
    ``UPDATE ... WHERE used_at IS NULL`` — a concurrent consumer of the same
    secret loses the row-count race and gets ``TokenError("used")``, making
    replays safe even under concurrency. Callers that mutate the user as a
    side effect (the services layer) wrap this call and the mutation in one
    ``transaction.atomic()`` block.

    :returns: the consumed :class:`~karni.accounts.models.OneTimeToken`, with
        ``used_at`` set.
    :raises TokenError: with reason ``"invalid"``, ``"used"`` or
        ``"expired"``.
    :raises ValueError: when ``purpose`` is not a known purpose value.
    """
    _require_known_purpose(purpose)
    try:
        token = OneTimeToken.objects.get(token_hash=hash_secret(secret), purpose=purpose)
    except OneTimeToken.DoesNotExist:
        raise TokenError("invalid") from None
    if token.used_at is not None:
        raise TokenError("used")
    now = timezone.now()
    if token.expires_at <= now:
        raise TokenError("expired")
    claimed = OneTimeToken.objects.filter(pk=token.pk, used_at__isnull=True).update(used_at=now)
    if not claimed:
        raise TokenError("used")
    token.used_at = now
    return token


def _require_known_purpose(purpose: str) -> None:
    """Reject purposes outside ``OneTimeToken.Purpose`` with a clear error."""
    if purpose not in OneTimeToken.Purpose.values:
        known = ", ".join(OneTimeToken.Purpose.values)
        raise ValueError(f"Unknown token purpose {purpose!r}; expected one of: {known}.")
