"""JWT mode: tokens for the target that carry the session, bounded by its time limit."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from karni_impersonation.models import ImpersonationSession

__all__ = ["CLAIM", "issue_for_actor", "issue_for_session", "session_id_from_token"]

#: The claim an impersonation token carries: the session's primary key.
CLAIM = "imp"


def _bounded(default: timedelta, until: Any) -> timedelta:
    remaining = until - timezone.now()
    if remaining <= timedelta(0):
        return timedelta(seconds=1)
    return min(default, remaining)


def issue_for_session(session: ImpersonationSession) -> dict[str, str]:
    """Tokens for the target with the ``imp`` claim; neither outlives the session."""
    refresh = RefreshToken.for_user(session.target)
    refresh[CLAIM] = str(session.pk)
    refresh.set_exp(lifetime=_bounded(api_settings.REFRESH_TOKEN_LIFETIME, session.expires_at))
    access = refresh.access_token
    access.set_exp(lifetime=_bounded(api_settings.ACCESS_TOKEN_LIFETIME, session.expires_at))
    return {"access": str(access), "refresh": str(refresh)}


def issue_for_actor(actor: Any) -> dict[str, str]:
    """Fresh, ordinary tokens for the impersonator — what ``stop`` hands back."""
    refresh = RefreshToken.for_user(actor)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def session_id_from_token(raw: str) -> str | None:
    """The ``imp`` claim of a valid access token, or ``None`` (invalid tokens are DRF's job)."""
    try:
        token = AccessToken(cast(Any, raw))
    except TokenError:
        return None
    value = token.get(CLAIM)
    return str(value) if value else None
