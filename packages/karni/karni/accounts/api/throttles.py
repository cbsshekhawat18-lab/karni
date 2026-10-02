"""Rate limiting for the auth endpoints (contract §Rate limiting, amendment A5).

Two throttle classes cover the auth surface:

* :class:`AuthScopedRateThrottle` — DRF's per-caller ``ScopedRateThrottle``
  (authenticated user id, or client IP honouring ``NUM_PROXIES``) that falls
  back to Karni's documented auth rates when a scope is missing from
  ``DEFAULT_THROTTLE_RATES``, so auth endpoints stay protected even in a
  project that replaces the ``REST_FRAMEWORK`` dict wholesale.
* :class:`AccountRateThrottle` — the amendment-A5 per-*account* login
  throttle, keyed on the normalized posted email instead of the caller, so a
  distributed credential-stuffing run against one mailbox is bounded no
  matter how many source IPs it uses.

Counters live in DRF's throttle cache (the ``default`` cache — Redis in a
Karni deployment via :mod:`karni.conf`, LocMem in the test suite).

Override / escape hatch: rates come from the ``KARNI_AUTH_THROTTLE_RATES``
setting, merged by ``karni.conf`` into
``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``; set any scope to ``None`` to
disable it. Subclass and swap ``throttle_classes`` on a view for anything
structural (a different identity key, a Redis-cluster cache, ...).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from rest_framework.request import Request
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView

__all__ = [
    "DEFAULT_AUTH_THROTTLE_RATES",
    "AccountRateThrottle",
    "AuthScopedRateThrottle",
]

DEFAULT_AUTH_THROTTLE_RATES: dict[str, str | None] = {
    "auth.login": "10/min",
    "auth.login_account": "10/hour",
    "auth.register": "10/hour",
    "auth.password_reset": "5/hour",
    "auth.token": "30/min",
    "auth.verify": "10/hour",
    "auth.email_change": "5/hour",
    "auth.2fa": "10/min",
}
"""Contract-default rates per auth scope, used only as a fallback when a scope
is absent from ``DEFAULT_THROTTLE_RATES`` (``karni.conf`` normally merges the
``KARNI_AUTH_THROTTLE_RATES`` setting in there, which then wins)."""


class _AuthRateFallbackMixin(SimpleRateThrottle):
    """``get_rate`` that prefers settings but never dies on a missing scope.

    Settings win: a scope present in ``DEFAULT_THROTTLE_RATES`` is used as-is,
    including an explicit ``None`` (the documented "disable this scope" escape
    hatch). Only a scope missing entirely falls back to
    :data:`DEFAULT_AUTH_THROTTLE_RATES`; an unknown scope ends up unthrottled
    instead of raising ``ImproperlyConfigured`` mid-request.
    """

    def get_rate(self) -> str | None:
        if self.scope in self.THROTTLE_RATES:
            rate: str | None = self.THROTTLE_RATES[self.scope]
            return rate
        return DEFAULT_AUTH_THROTTLE_RATES.get(self.scope)


class AuthScopedRateThrottle(_AuthRateFallbackMixin, ScopedRateThrottle):
    """Per-IP / per-user scoped throttle for the auth endpoints.

    Behaves exactly like DRF's ``ScopedRateThrottle`` (reads the view's
    ``throttle_scope``; ``NUM_PROXIES`` — ``KARNI_NUM_PROXIES`` in the
    environment, default 1 behind the shipped Caddy — governs which IP counts
    for anonymous callers, amendment A5) but with the Karni fallback rates of
    :class:`_AuthRateFallbackMixin`.
    """


class AccountRateThrottle(_AuthRateFallbackMixin):
    """Per-account login throttle keyed on the posted email (amendment A5).

    Applied to ``login/`` alongside the per-IP scoped throttle: the cache key
    is derived from the *normalized posted email* (lower-cased, hashed — raw
    addresses never appear in cache keys), so attempts against one account are
    bounded across source IPs. Default rate ``10/hour`` under the scope
    ``auth.login_account`` (same ``KARNI_AUTH_THROTTLE_RATES`` override path;
    ``None`` disables). A request without a usable ``email`` field is not
    throttled here — the per-IP scope still covers it.

    Override / escape hatch: subclass and override :meth:`get_account_ident`
    to key on another posted field (``karni.accounts.twofa`` does exactly
    that for ``2fa/login/``, keying on the ephemeral token's hash).
    """

    scope = "auth.login_account"

    def get_account_ident(self, request: Request) -> str | None:
        """The normalized account identity in ``request``, or ``None``."""
        data = request.data
        if not isinstance(data, Mapping):
            return None
        email = data.get("email")
        if not isinstance(email, str) or not email.strip():
            return None
        return email.strip().lower()

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        ident = self.get_account_ident(request)
        if ident is None:
            return None
        digest = hashlib.sha256(ident.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}
