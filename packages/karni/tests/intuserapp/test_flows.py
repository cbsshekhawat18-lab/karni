"""Karni's accounts flows with an integer-keyed user (``AUTH_USER_MODEL = "intuserapp.User"``).

Runs only in the subprocess ``tests/accounts/test_integer_user.py`` starts
with ``KARNI_TEST_USER_PK=bigint``. Each flow is the one its own test module
covers in depth, here once end to end with a user whose ``id`` is a
``BigAutoField``: login and refresh in JWT and session mode, ``me/``, roles,
the 2FA login gate, sign-in with an ID token, sign-in with a code sent by
email, the terms gate, per-user grants and the menu from data.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import models
from django.urls import include, path
from pytest_django import Settings
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import AccessToken

from karni.accounts.permissions import assign_role
from karni.accounts.urls import build_urlpatterns

pytestmark = pytest.mark.django_db

PASSWORD = "integer-user-pass-123!"
SCOPES = (
    "auth.login",
    "auth.login_account",
    "auth.refresh",
    "auth.2fa",
    "auth.social",
    "auth.otp_send",
    "auth.otp_send_email",
    "auth.otp_verify",
)


def _urlconf() -> ModuleType:
    """A URLconf built for the settings of the test (the accounts routes are built once)."""
    from django.contrib import admin

    module = ModuleType("integer_user_urls")
    module.__dict__["urlpatterns"] = [
        path("admin/", admin.site.urls),
        path("api/auth/", include(build_urlpatterns())),
        path("api/", include("karni.api.urls")),
    ]
    return module


@pytest.fixture(autouse=True)
def _fresh(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    cache.clear()
    settings.KARNI_AUTH_MODE = "jwt"
    for scope in SCOPES:
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, "1000/min")
    settings.ROOT_URLCONF = _urlconf()
    yield
    cache.clear()


def _user(email: str = "ada@example.com", **extra: Any) -> Any:
    return get_user_model().objects.create_user(email=email, password=PASSWORD, **extra)


def _login(client: APIClient, email: str = "ada@example.com") -> Any:
    return client.post("/api/auth/login/", {"email": email, "password": PASSWORD}, format="json")


def _bearer(access: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


def test_the_user_model_has_an_integer_key() -> None:
    model = get_user_model()
    assert model._meta.label == "intuserapp.User"
    assert isinstance(model._meta.pk, models.BigAutoField)
    first, second = _user(), _user("grace@example.com")
    assert isinstance(first.pk, int) and second.pk == first.pk + 1


def test_jwt_login_refresh_and_me() -> None:
    user = _user()
    response = _login(APIClient())
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["user"]["id"] == user.pk  # a JSON number
    assert AccessToken(body["access"])["user_id"] in (user.pk, str(user.pk))
    me = _bearer(body["access"]).get("/api/auth/me/")
    assert me.status_code == 200 and me.json()["id"] == user.pk
    refreshed = APIClient().post("/api/auth/refresh/", {"refresh": body["refresh"]}, format="json")
    assert refreshed.status_code == 200, refreshed.content
    assert _bearer(refreshed.json()["access"]).get("/api/auth/me/").json()["email"] == user.email


def test_session_login_and_me(settings: Settings) -> None:
    settings.KARNI_AUTH_MODE = "session"
    user = _user()
    client = APIClient(enforce_csrf_checks=False)
    assert _login(client).status_code == 200
    me = client.get("/api/auth/me/")
    assert me.status_code == 200 and me.json()["id"] == user.pk


def test_roles_gate_the_api_and_reach_rows_by_integer_id() -> None:
    staff, member = _user("staff@example.com"), _user()
    assign_role(staff, "staff")
    assert staff.has_role("staff") and not member.has_role("staff")
    token = _login(APIClient(), "staff@example.com").json()["access"]
    client = _bearer(token)
    listed = client.get("/api/users/")
    assert listed.status_code == 200, listed.content
    assert {row["id"] for row in listed.json()["results"]} == {staff.pk, member.pk}
    changed = client.patch(f"/api/users/{member.pk}/", {"first_name": "Ada"}, format="json")
    assert changed.status_code == 200, changed.content
    refused = _bearer(_login(APIClient()).json()["access"]).patch(
        f"/api/users/{staff.pk}/", {"first_name": "X"}, format="json"
    )
    assert refused.status_code == 403
    me = client.get("/api/auth/me/").json()
    assert me["roles"] == ["staff"]


def test_the_2fa_login_gate(settings: Settings) -> None:
    pytest.importorskip("django_otp")
    from django_otp.oath import totp
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from karni.accounts import twofa

    user = _user()
    twofa.setup_totp(user)
    device = TOTPDevice.objects.devices_for_user(user, confirmed=False).get()

    def code() -> str:
        value = totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits)
        return f"{value:0{device.digits}d}"

    twofa.confirm_totp(user, code())
    device.refresh_from_db()
    device.last_t = -1
    device.save()
    settings.KARNI_2FA = True
    settings.ROOT_URLCONF = _urlconf()  # the 2fa/ routes exist while KARNI_2FA is on
    gated = _login(APIClient())
    assert gated.status_code == 200 and gated.json()["requires_2fa"] is True
    assert "access" not in gated.json()
    exchanged = APIClient().post(
        "/api/auth/2fa/login/",
        {"ephemeral_token": gated.json()["ephemeral_token"], "code": code()},
        format="json",
    )
    assert exchanged.status_code == 200, exchanged.content
    assert exchanged.json()["user"]["id"] == user.pk


def test_sign_in_with_an_id_token(settings: Settings) -> None:
    pytest.importorskip("jwt")
    from karni.accounts.models import SocialIdentity
    from tests.accounts import idtokens

    idtokens.reset()
    settings.KARNI_SOCIAL_TOKEN_PROVIDERS = copy.deepcopy(idtokens.PROVIDERS)
    settings.KARNI_SOCIAL_TOKEN_JWKS_FETCHER = idtokens.FETCHER
    settings.ROOT_URLCONF = _urlconf()
    response = APIClient().post(
        "/api/auth/social/google/", {"id_token": idtokens.mint("google")}, format="json"
    )
    assert response.status_code == 200, response.content
    user = get_user_model().objects.get(email="ada@example.com")
    assert isinstance(user.pk, int) and response.json()["user"]["id"] == user.pk
    assert SocialIdentity.objects.get(provider="google").user_id == user.pk
    again = APIClient().post(
        "/api/auth/social/google/", {"id_token": idtokens.mint("google")}, format="json"
    )
    assert again.status_code == 200 and again.json()["user"]["id"] == user.pk


def test_sign_in_with_a_code_sent_by_email(
    settings: Settings, django_capture_on_commit_callbacks: Any
) -> None:
    from karni.accounts.emails import InMemoryEmailBackend
    from karni.accounts.models import LoginCode

    InMemoryEmailBackend.clear()
    settings.KARNI_ACCOUNTS_EMAIL_BACKEND = "karni.accounts.emails.InMemoryEmailBackend"
    settings.KARNI_EMAIL_OTP = True
    settings.ROOT_URLCONF = _urlconf()
    user = _user()
    with django_capture_on_commit_callbacks(execute=True):
        sent = APIClient().post("/api/auth/otp/send/", {"email": user.email}, format="json")
    assert sent.status_code in (200, 202), sent.content
    code = str(InMemoryEmailBackend.outbox[-1].context["code"])
    assert LoginCode.objects.filter(email=user.email).exists()
    verified = APIClient().post(
        "/api/auth/otp/verify/", {"email": user.email, "code": code}, format="json"
    )
    assert verified.status_code == 200, verified.content
    assert verified.json()["user"]["id"] == user.pk
    InMemoryEmailBackend.clear()


def test_the_terms_gate(settings: Settings) -> None:
    from karni.accounts.models import TermsAcceptance

    settings.KARNI_TERMS = {"version": "2026-11", "url": "/terms/", "required": True}
    settings.ROOT_URLCONF = _urlconf()
    user = _user()
    client = _bearer(_login(APIClient()).json()["access"])
    gated = client.get("/api/users/")
    assert gated.status_code == 403 and gated.json()["code"] == "E245"
    accepted = client.post("/api/auth/terms/accept/", {"version": "2026-11"}, format="json")
    assert accepted.status_code == 201, accepted.content
    assert TermsAcceptance.objects.get().user_id == user.pk
    assert client.get("/api/users/").status_code == 200
    assert client.get("/api/auth/me/").json()["terms"]["accepted"] is True


def test_per_user_grants_with_integer_users(settings: Settings) -> None:
    from karni.accounts.models import UserGrant
    from karni.accounts.roles import user_can

    settings.KARNI_USER_GRANTS = True
    settings.ROOT_URLCONF = _urlconf()
    staff, member = _user("staff@example.com"), _user()
    assign_role(staff, "staff")
    staff_client = _bearer(_login(APIClient(), "staff@example.com").json()["access"])
    created = staff_client.post(
        "/api/auth/permissions/grants/",
        {"user": member.pk, "permission": "intuserapp.user:view", "scope": "all"},
        format="json",
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["user"] == member.pk and body["granted_by"] == staff.pk  # JSON numbers
    assert UserGrant.objects.get().granted_by_id == staff.pk
    assert user_can(get_user_model().objects.get(pk=member.pk), "intuserapp.user:view")
    listed = staff_client.get("/api/auth/permissions/grants/", {"user": member.pk}).json()
    assert [row["id"] for row in listed["results"]] == [body["id"]]
    mine = _bearer(_login(APIClient()).json()["access"]).get("/api/auth/permissions/effective/")
    entry = next(e for e in mine.json()["permissions"] if e["permission"] == "intuserapp.user:view")
    assert [source["origin"] for source in entry["sources"]] == ["user_grant"]


def test_the_menu_with_integer_users(settings: Settings) -> None:
    """Navigation (experimental): a user grant opens an item, and the admin previews by id."""
    from django.contrib.auth.models import Permission
    from django.test import Client

    from karni.accounts import grants
    from karni.navigation.api import build_urlpatterns as build_navigation_urls
    from karni.navigation.models import NavItem

    settings.KARNI_USER_GRANTS = True
    settings.KARNI_NAVIGATION = "db"
    urls = _urlconf()  # karni.api.urls was imported while the menu was off: mount it here
    urls.urlpatterns.insert(0, path("api/", include(build_navigation_urls())))
    settings.ROOT_URLCONF = urls
    people = NavItem.objects.create(label="People", requires="authenticated")
    NavItem.objects.create(
        label="Users", route="/users", requires="intuserapp.user:view", parent=people
    )
    NavItem.objects.create(label="Home", route="/", requires="public")
    member = _user()
    client = _bearer(_login(APIClient()).json()["access"])
    assert client.get("/api/navigation/").json()["items"] == [
        {"label": "Home", "icon": None, "route": "/", "children": []}
    ]
    grants.grant(None, member, "intuserapp.user:view")
    labels = [item["label"] for item in client.get("/api/navigation/").json()["items"]]
    assert labels == ["People", "Home"]
    staff = _user("staff@example.com", is_staff=True, is_superuser=True)
    staff.user_permissions.add(Permission.objects.get(codename="view_navitem"))
    browser = Client()
    browser.force_login(staff)
    page = browser.get("/admin/karni_navigation/navitem/preview/", {"user": str(member.pk)})
    assert page.status_code == 200 and "<code>/users</code>" in page.content.decode()
