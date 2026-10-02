"""Tests for :mod:`karni.accounts.tokens`: issue/consume, TTLs, replay safety."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.test import override_settings
from django.utils import timezone

from karni.accounts.models import OneTimeToken, User
from karni.accounts.tokens import (
    DEFAULT_TOKEN_TTL,
    TokenError,
    consume_token,
    hash_secret,
    issue_token,
    token_ttl,
)

from .factories import UserFactory

VERIFY = OneTimeToken.Purpose.VERIFY_EMAIL
RESET = OneTimeToken.Purpose.RESET_PASSWORD
CHANGE = OneTimeToken.Purpose.CHANGE_EMAIL


@pytest.fixture
def user(db: Any) -> User:
    return UserFactory()


def _row(secret: str) -> OneTimeToken:
    return OneTimeToken.objects.get(token_hash=hash_secret(secret))


# --- model shape --------------------------------------------------------------


def test_token_model_declaration() -> None:
    assert OneTimeToken._meta.get_field("token_hash").unique is True
    assert set(OneTimeToken.Purpose.values) == {
        "verify_email",
        "reset_password",
        "change_email",
    }
    user_field = OneTimeToken._meta.get_field("user")
    assert user_field.remote_field.related_name == "one_time_tokens"


# --- issuing ------------------------------------------------------------------


def test_issue_returns_secret_and_stores_only_its_hash(user: User) -> None:
    secret = issue_token(user, VERIFY)

    assert isinstance(secret, str)
    assert len(secret) >= 43  # token_urlsafe(32)
    token = _row(secret)
    assert token.user == user
    assert token.purpose == VERIFY
    assert token.used_at is None
    assert token.new_email is None
    assert token.token_hash != secret
    assert not OneTimeToken.objects.filter(token_hash=secret).exists()


@pytest.mark.parametrize(
    ("purpose", "ttl"),
    [(VERIFY, 86400), (RESET, 3600), (CHANGE, 86400)],
)
def test_default_ttl_per_purpose(user: User, purpose: str, ttl: int) -> None:
    assert DEFAULT_TOKEN_TTL[purpose] == ttl
    before = timezone.now()
    secret = issue_token(user, purpose)
    delta = _row(secret).expires_at - before
    assert timedelta(seconds=ttl - 30) < delta <= timedelta(seconds=ttl + 30)


@override_settings(KARNI_ACCOUNTS_TOKEN_TTL={"reset_password": 60})
def test_ttl_setting_overrides_per_key(user: User) -> None:
    """A partial ``KARNI_ACCOUNTS_TOKEN_TTL`` dict overrides only its keys."""
    assert token_ttl(RESET) == 60
    assert token_ttl(VERIFY) == 86400
    before = timezone.now()
    secret = issue_token(user, RESET)
    delta = _row(secret).expires_at - before
    assert delta <= timedelta(seconds=90)


def test_issue_stores_new_email_for_change_flow(user: User) -> None:
    secret = issue_token(user, CHANGE, new_email="new@example.com")
    assert _row(secret).new_email == "new@example.com"


def test_issue_rejects_unknown_purpose(user: User) -> None:
    with pytest.raises(ValueError, match="Unknown token purpose"):
        issue_token(user, "impersonate")


def test_reissue_invalidates_prior_unused_token(user: User) -> None:
    first = issue_token(user, VERIFY)
    second = issue_token(user, VERIFY)

    # The first row still exists but is marked used, not deleted.
    assert _row(first).used_at is not None
    with pytest.raises(TokenError) as excinfo:
        consume_token(first, VERIFY)
    assert excinfo.value.reason == "used"
    assert consume_token(second, VERIFY).pk == _row(second).pk


def test_reissue_is_scoped_to_user_and_purpose(user: User) -> None:
    other_user: User = UserFactory()
    reset_secret = issue_token(user, RESET)
    other_secret = issue_token(other_user, VERIFY)

    issue_token(user, VERIFY)  # invalidates only (user, verify_email) tokens

    assert _row(reset_secret).used_at is None
    assert _row(other_secret).used_at is None
    assert consume_token(reset_secret, RESET).user == user
    assert consume_token(other_secret, VERIFY).user == other_user


# --- consuming ----------------------------------------------------------------


def test_consume_marks_used_and_persists(user: User) -> None:
    secret = issue_token(user, VERIFY)
    token = consume_token(secret, VERIFY)

    assert token.used_at is not None
    assert _row(secret).used_at is not None


def test_consume_unknown_secret_is_invalid(db: Any) -> None:
    with pytest.raises(TokenError) as excinfo:
        consume_token("no-such-secret", VERIFY)
    assert excinfo.value.reason == "invalid"


def test_consume_wrong_purpose_is_invalid(user: User) -> None:
    secret = issue_token(user, VERIFY)
    with pytest.raises(TokenError) as excinfo:
        consume_token(secret, RESET)
    assert excinfo.value.reason == "invalid"
    # The token was not consumed by the failed attempt.
    assert _row(secret).used_at is None


def test_consume_twice_is_used(user: User) -> None:
    secret = issue_token(user, VERIFY)
    consume_token(secret, VERIFY)
    with pytest.raises(TokenError) as excinfo:
        consume_token(secret, VERIFY)
    assert excinfo.value.reason == "used"


def test_consume_expired_token(user: User) -> None:
    secret = issue_token(user, VERIFY)
    OneTimeToken.objects.filter(token_hash=hash_secret(secret)).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(TokenError) as excinfo:
        consume_token(secret, VERIFY)
    assert excinfo.value.reason == "expired"
    assert _row(secret).used_at is None


def test_consume_rejects_unknown_purpose(db: Any) -> None:
    with pytest.raises(ValueError, match="Unknown token purpose"):
        consume_token("whatever", "impersonate")


def test_concurrent_consume_loses_the_claim_race(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay safety under concurrency.

    Simulates the race deterministically: a competing consumer claims the
    token between our initial ``get`` and the claiming ``UPDATE``, so our
    in-memory snapshot still looks unused. The row-count check on
    ``filter(used_at__isnull=True).update(...)`` must detect the lost race.
    """
    secret = issue_token(user, VERIFY)
    real_get = OneTimeToken.objects.get

    def racing_get(*args: Any, **kwargs: Any) -> OneTimeToken:
        token = real_get(*args, **kwargs)
        OneTimeToken.objects.filter(pk=token.pk).update(used_at=timezone.now())
        return token  # stale snapshot: used_at is still None in memory

    monkeypatch.setattr(OneTimeToken.objects, "get", racing_get)
    with pytest.raises(TokenError) as excinfo:
        consume_token(secret, VERIFY)
    assert excinfo.value.reason == "used"


def test_token_error_carries_reason() -> None:
    error = TokenError("expired")
    assert error.reason == "expired"
    assert "expired" in str(error)


# --- lifecycle ----------------------------------------------------------------


def test_related_name_and_cascade_delete(user: User) -> None:
    issue_token(user, VERIFY)
    issue_token(user, RESET)
    assert user.one_time_tokens.count() == 2

    user.delete()

    assert OneTimeToken.objects.count() == 0
