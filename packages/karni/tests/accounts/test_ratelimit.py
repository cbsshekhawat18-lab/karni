"""Throttling tests for the auth endpoints (accounts contract §Rate limiting + A5).

DRF throttling stores request history in ``caches["default"]`` — locmem in
the test settings, Redis in production via ``karni.conf``. Every test clears
that cache so scopes never bleed between tests.

Rates are patched directly on ``SimpleRateThrottle.THROTTLE_RATES`` (the very
dict DRF resolves scopes against, bound once from
``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``): DRF binds it at import time,
so ``override_settings(REST_FRAMEWORK=...)`` would not reach it. In a project
the same dict is fed from ``KARNI_AUTH_THROTTLE_RATES``, which ``karni.conf``
merges into ``DEFAULT_THROTTLE_RATES`` — that is the supported override path
documented in docs/accounts.md.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

import pytest
from django.core.cache import cache
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from karni.accounts.twofa import TwoFAAccountRateThrottle

pytestmark = pytest.mark.django_db

LOGIN_URL = "/api/auth/login/"
PASSWORD_RESET_URL = "/api/auth/password/reset/"

RateSetter = Callable[[dict[str, str | None]], None]


@pytest.fixture(autouse=True)
def _clean_throttle_cache() -> Any:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def set_rates(monkeypatch: pytest.MonkeyPatch) -> RateSetter:
    def _set(mapping: dict[str, str | None]) -> None:
        for scope, rate in mapping.items():
            monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, rate)

    return _set


@pytest.fixture
def user(django_user_model: Any) -> Any:
    return django_user_model.objects.create_user(
        email="throttled@example.com", password="s3cret-pass-123"
    )


def _login(client: APIClient, email: str, *, ip: str | None = None) -> Any:
    extra: dict[str, str] = {}
    if ip is not None:
        # Cover both throttle identities: REMOTE_ADDR (no NUM_PROXIES) and
        # X-Forwarded-For (NUM_PROXIES=1 behind Caddy, amendment A5).
        extra = {"REMOTE_ADDR": ip, "HTTP_X_FORWARDED_FOR": ip}
    return client.post(
        LOGIN_URL, {"email": email, "password": "wrong-password"}, format="json", **extra
    )


class TestScopedThrottling:
    def test_login_throttled_per_ip_after_limit(self, set_rates: RateSetter) -> None:
        set_rates({"auth.login": "3/min", "auth.login_account": None})
        client = APIClient()
        for i in range(3):
            response = _login(client, f"nobody{i}@example.com")
            assert response.status_code != 429
        response = _login(client, "nobody-final@example.com")
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    def test_scopes_are_independent(self, set_rates: RateSetter) -> None:
        set_rates(
            {
                "auth.login": "1/min",
                "auth.login_account": None,
                "auth.password_reset": "100/hour",
            }
        )
        client = APIClient()
        assert _login(client, "nobody@example.com").status_code != 429
        assert _login(client, "nobody@example.com").status_code == 429
        # Exhausting auth.login must not consume auth.password_reset.
        response = client.post(PASSWORD_RESET_URL, {"email": "nobody@example.com"}, format="json")
        assert response.status_code != 429

    def test_rate_override_changes_limit(self, set_rates: RateSetter) -> None:
        # In a project this dict entry comes from KARNI_AUTH_THROTTLE_RATES;
        # tightening it to 1/min must take effect immediately.
        set_rates({"auth.login": "1/min", "auth.login_account": None})
        client = APIClient()
        assert _login(client, "solo@example.com").status_code != 429
        assert _login(client, "solo@example.com").status_code == 429

    def test_none_rate_disables_throttle(self, set_rates: RateSetter) -> None:
        set_rates({"auth.login": None, "auth.login_account": None})
        client = APIClient()
        for i in range(20):
            response = _login(client, f"free{i}@example.com")
            assert response.status_code != 429


class TestPerAccountThrottling:
    def test_same_email_across_ips_is_throttled(self, set_rates: RateSetter, user: Any) -> None:
        # Amendment A5/A13: rotating IPs must not evade the per-account limit.
        set_rates({"auth.login": "1000/min", "auth.login_account": "3/hour"})
        client = APIClient()
        for i in range(3):
            response = _login(client, user.email, ip=f"10.0.0.{i + 1}")
            assert response.status_code != 429
        response = _login(client, user.email, ip="10.0.0.99")
        assert response.status_code == 429

    def test_other_account_not_affected(self, set_rates: RateSetter, user: Any) -> None:
        set_rates({"auth.login": "1000/min", "auth.login_account": "2/hour"})
        client = APIClient()
        for i in range(2):
            assert _login(client, user.email, ip=f"10.0.1.{i + 1}").status_code != 429
        assert _login(client, user.email, ip="10.0.1.50").status_code == 429
        # A different account from yet another IP is still allowed.
        assert _login(client, "someone-else@example.com", ip="10.0.1.51").status_code != 429


# TwoFAAccountRateThrottle unit tests
#
# The 2fa/login/ variant of the amendment-A5 per-account throttle: email when
# present, otherwise the posted ephemeral_token identifies the "account".


class _ThrottledView(APIView):
    authentication_classes: ClassVar[list[Any]] = []
    permission_classes: ClassVar[list[Any]] = [AllowAny]
    throttle_classes: ClassVar[list[Any]] = [TwoFAAccountRateThrottle]

    def post(self, request: Any) -> Response:
        return Response({"ok": True})


def _post_direct(data: dict[str, Any], ip: str) -> Any:
    request = APIRequestFactory().post("/throttled/", data, format="json", REMOTE_ADDR=ip)
    return _ThrottledView.as_view()(request)


class TestTwoFAAccountRateThrottleUnit:
    def test_keys_on_normalized_email_across_ips(self, set_rates: RateSetter) -> None:
        set_rates({"auth.login_account": "2/hour"})
        assert _post_direct({"email": "Case@Example.com"}, "10.1.0.1").status_code == 200
        # Same account, different IP and different casing/whitespace.
        assert _post_direct({"email": "  case@example.com "}, "10.1.0.2").status_code == 200
        assert _post_direct({"email": "case@EXAMPLE.com"}, "10.1.0.3").status_code == 429
        # A different account is unaffected.
        assert _post_direct({"email": "fresh@example.com"}, "10.1.0.4").status_code == 200

    def test_falls_back_to_ephemeral_token_identity(self, set_rates: RateSetter) -> None:
        set_rates({"auth.login_account": "1/hour"})
        payload = {"ephemeral_token": "signed-token", "code": "123456"}
        assert _post_direct(payload, "10.2.0.1").status_code == 200
        assert _post_direct(payload, "10.2.0.2").status_code == 429
        other = {"ephemeral_token": "other-token", "code": "123456"}
        assert _post_direct(other, "10.2.0.3").status_code == 200

    def test_email_wins_over_token_identity(self, set_rates: RateSetter) -> None:
        set_rates({"auth.login_account": "1/hour"})
        both = {"email": "gate@example.com", "ephemeral_token": "tok-1", "code": "123456"}
        assert _post_direct(both, "10.6.0.1").status_code == 200
        # Same email, different token: still the same identity bucket.
        both_other_token = {**both, "ephemeral_token": "tok-2"}
        assert _post_direct(both_other_token, "10.6.0.2").status_code == 429

    def test_without_identity_it_does_not_throttle(self, set_rates: RateSetter) -> None:
        set_rates({"auth.login_account": "1/hour"})
        for _ in range(5):
            assert _post_direct({"something": "else"}, "10.3.0.1").status_code == 200

    def test_none_rate_disables(self, set_rates: RateSetter) -> None:
        set_rates({"auth.login_account": None})
        for _ in range(5):
            assert _post_direct({"email": "unlimited@example.com"}, "10.5.0.1").status_code == 200
